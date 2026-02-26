# Copyright 2020 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import logging
import os
import pkgutil
import re
import shutil
import sys
from collections import defaultdict
from contextlib import closing
from fileinput import FileInput
from textwrap import dedent

from pex.atomic_directory import AtomicDirectory, atomic_directory
from pex.common import safe_mkdir, safe_mkdtemp, safe_open
from pex.compatibility import get_stdout_bytes_buffer, safe_commonpath
from pex.dist_metadata import Distribution, find_distributions
from pex.enum import Enum
from pex.executor import Executor
from pex.fetcher import URLFetcher
from pex.fs import safe_symlink
from pex.interpreter import (
    Platlib,
    Purelib,
    PythonInterpreter,
    PyVenvCfg,
    SitePackagesDir,
    create_shebang,
)
from pex.orderedset import OrderedSet
from pex.os import is_exe
from pex.sysconfig import SCRIPT_DIR, script_name
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.util import named_temporary_file
from pex.variables import ENV
from pex.version import __version__

if TYPE_CHECKING:
    from typing import DefaultDict, Iterable, Iterator, Optional, Tuple, Type, Union

logger = logging.getLogger(__name__)


class PipUnavailableError(Exception):
    """Indicates no local copy of Pip could be found for install."""


def _iter_files(directory):
    # type: (str) -> Iterator[str]
    for entry in os.listdir(directory):
        yield os.path.join(directory, entry)


def _is_python_script(executable):
    # type: (str) -> bool
    with open(executable, "rb") as fp:
        if fp.read(2) != b"#!":
            return False
        interpreter = fp.readline()
        return bool(
            # Support the `#!python` shebang that wheel installers should recognize as a special
            # form to convert to a localized shebang upon install.
            # See: https://peps.python.org/pep-0427/#recommended-installer-features
            interpreter == b"python\n"
            or re.search(
                br"""
                # The aim is to admit the common shebang forms:
                # + /usr/bin/env <python bin name>
                # + /absolute/path/to/<python bin name>
                \W

                # Python executable names Pex supports (see PythonIdentity).
                (
                      python
                    | pypy
                )
                # Optional Python version
                (\d+(\.\d+)*)?

                ([^.a-zA-Z0-9]|$)
                """,
                interpreter,
                re.VERBOSE,
            )
        )


class InvalidVirtualenvError(Exception):
    """Indicates a virtualenv is malformed."""


def _find_preferred_site_packages_dir(
    venv_dir,  # type: str
    interpreter=None,  # type: Optional[PythonInterpreter]
):
    # type: (...) -> str

    real_venv_dir = os.path.realpath(venv_dir)
    site_packages_dirs_by_type = defaultdict(
        OrderedSet
    )  # type: DefaultDict[Type[SitePackagesDir], OrderedSet[SitePackagesDir]]

    interpreter = interpreter or PythonInterpreter.get()
    for entry in interpreter.site_packages:
        if safe_commonpath((real_venv_dir, entry.path)) != real_venv_dir:
            # This ignores system site packages when the venv is built with --system-site-packages.
            continue
        if os.path.isdir(entry.path):
            site_packages_dirs_by_type[type(entry)].add(entry)

    if not site_packages_dirs_by_type:
        raise InvalidVirtualenvError(
            "The virtualenv at {venv_dir} is not valid. No site-packages directory was found in "
            "its sys.path:\n{sys_path}".format(
                venv_dir=venv_dir, sys_path="\n".join(interpreter.sys_path)
            )
        )

    for site_packages_dir_type in Purelib, Platlib, SitePackagesDir:
        site_packages_dirs = site_packages_dirs_by_type.get(site_packages_dir_type)
        if not site_packages_dirs:
            continue
        if len(site_packages_dirs) > 1:
            raise InvalidVirtualenvError(
                "The virtualenv at {venv_dir} is not valid. It has more than one {dir_type} "
                "directory:\n{site_packages}".format(
                    venv_dir=venv_dir,
                    dir_type=site_packages_dir_type,
                    site_packages="\n".join(entry.path for entry in site_packages_dirs),
                )
            )
        return site_packages_dirs.pop().path

    raise InvalidVirtualenvError(
        "Could not determine the site-packages directory for the venv at {venv_dir}.".format(
            venv_dir=venv_dir
        )
    )


class InstallationChoice(Enum["InstallationChoice.Value"]):
    class Value(Enum.Value):
        pass

    NO = Value("no")
    YES = Value("yes")
    UPGRADED = Value("upgraded")


InstallationChoice.seal()


class Virtualenv(object):
    VIRTUALENV_VERSION = "16.7.12"

    @classmethod
    def enclosing(cls, python):
        # type: (Union[str, PythonInterpreter]) -> Optional[Virtualenv]
        """Return the virtual environment the given python interpreter is enclosed in."""
        if isinstance(python, PythonInterpreter):
            interpreter = python
        else:
            try:
                interpreter = PythonInterpreter.from_binary(python)
            except PythonInterpreter.Error:
                return None

        if not interpreter.is_venv:
            return None
        return cls(
            venv_dir=interpreter.prefix, python_exe_name=os.path.basename(interpreter.binary)
        )

    @classmethod
    def create(
        cls,
        venv_dir,  # type: str
        interpreter=None,  # type: Optional[PythonInterpreter]
        force=False,  # type: bool
        copies=False,  # type: bool
        system_site_packages=False,  # type: bool
        prompt=None,  # type: Optional[str]
        install_pip=InstallationChoice.NO,  # type: InstallationChoice.Value
        install_setuptools=InstallationChoice.NO,  # type: InstallationChoice.Value
        install_wheel=InstallationChoice.NO,  # type: InstallationChoice.Value
        other_installs=(),  # type: Iterable[str]
        cwd=None,  # type: Optional[str]  # N.B.: For tests.
    ):
        # type: (...) -> Virtualenv

        installations = {
            "pip": install_pip,
            "setuptools": install_setuptools,
            "wheel": install_wheel,
        }
        project_upgrades = [
            project
            for project, installation_choice in installations.items()
            if installation_choice is InstallationChoice.UPGRADED
        ]
        if project_upgrades and install_pip is InstallationChoice.NO:
            raise ValueError(
                "Installation of Pip is required in order to upgrade {projects}.".format(
                    projects=" and ".join(project_upgrades)
                )
            )

        venv_dir = os.path.abspath(venv_dir)
        safe_mkdir(venv_dir, clean=force)

        interpreter = interpreter or PythonInterpreter.get()
        if interpreter.is_venv:
            base_interpreter = interpreter.resolve_base_interpreter()
            TRACER.log(
                "Ignoring enclosing venv {} and using its base interpreter {} to create venv at {}"
                " instead.".format(interpreter.prefix, base_interpreter.binary, venv_dir),
                V=3,
            )
            interpreter = base_interpreter

        # N.B.: PyPy3.6 and PyPy3.7 come equipped with a venv module but it does not seem to
        # work.
        py_major_minor = interpreter.version[:2]
        use_virtualenv = py_major_minor[0] == 2 or (
            interpreter.is_pypy and py_major_minor[:2] <= (3, 7)
        )

        installations.pop("pip")
        if install_pip is not InstallationChoice.NO and py_major_minor < (3, 12):
            # The ensure_pip module, get_pip.py and the venv module all install setuptools when
            # they install Pip for all Pythons older than 3.12.
            installations.pop("setuptools")

        project_installs = OrderedSet(
            project
            for project, installation_choice in installations.items()
            if installation_choice is InstallationChoice.YES
        )
        project_installs.update(other_installs)
        if project_installs and install_pip is InstallationChoice.NO:
            raise ValueError(
                "Installation of Pip is required in order to install {projects}.".format(
                    projects=" and ".join(project_installs)
                )
            )

        # Guard against API calls from environment with ambient PYTHONPATH preventing pip virtualenv
        # creation. See: https://github.com/pex-tool/pex/issues/1451
        env = os.environ.copy()
        pythonpath = env.pop("PYTHONPATH", None)
        if pythonpath:
            TRACER.log(
                "Scrubbed PYTHONPATH={} from the virtualenv creation environment.".format(
                    pythonpath
                ),
                V=3,
            )

        if interpreter.version < (3, 4):
            # N.B.: This isolates the venv creation process from PWD on older Pythons without -I or
            # -P support.
            cwd = safe_mkdtemp()

        custom_prompt = None  # type: Optional[str]
        if use_virtualenv:
            virtualenv_py = pkgutil.get_data(
                __name__, "virtualenv_{version}_py".format(version=cls.VIRTUALENV_VERSION)
            )
            with named_temporary_file(mode="wb") as fp:
                fp.write(virtualenv_py)
                fp.close()
                args = [fp.name, "--no-pip", "--no-setuptools", "--no-wheel", venv_dir]
                if copies:
                    args.append("--always-copy")
                if system_site_packages:
                    args.append("--system-site-packages")
                if prompt:
                    args.extend(["--prompt", prompt])
                    custom_prompt = prompt
                interpreter.execute(args=args, env=env, cwd=cwd)
                # Modern virtualenv provides a pyvenv.cfg; so we provide one on 16.7.12's behalf
                # since users might expect one. To ward off any confusion for readers of the emitted
                # pyvenv.cfg file, we add a bespoke created-by field to help make it clear that Pex
                # created the pyvenv.cfg file on virtualenv 16.7.12's behalf.
                # N.B.: This bespoke created-by "note" field is not related to the
                # Virtualenv.created_by property which reflects the underlying venv technology.
                # In this case it will report "virtualenv 16.7.12".
                with open(os.path.join(venv_dir, "pyvenv.cfg"), "w") as fp:
                    fp.write(
                        dedent(
                            """\
                            home = {home}
                            include-system-site-packages = {include_system_site_packages}
                            virtualenv = {virtualenv_version}
                            version = {python_version}
                            created-by = pex {pex_version}
                            """
                        ).format(
                            home=os.path.dirname(interpreter.binary),
                            include_system_site_packages=(
                                "true" if system_site_packages else "false"
                            ),
                            virtualenv_version=cls.VIRTUALENV_VERSION,
                            python_version=".".join(map(str, interpreter.version)),
                            pex_version=__version__,
                        )
                    )
        else:
            args = ["-m", "venv", venv_dir]
            if install_pip is InstallationChoice.NO:
                args.append("--without-pip")
            if copies:
                args.append("--copies")
            if system_site_packages:
                args.append("--system-site-packages")
            if prompt and py_major_minor >= (3, 6):
                args.extend(["--prompt", prompt])
                custom_prompt = prompt
            interpreter.execute(args=args, env=env, cwd=cwd)

        venv = cls(venv_dir, custom_prompt=custom_prompt)
        if use_virtualenv and (
            install_pip is not InstallationChoice.NO or project_upgrades or project_installs
        ):
            # Our vendored virtualenv does not support installing Pip, setuptool or wheel; so we
            # use the ensurepip module / get_pip.py bootstrapping for Pip that `ensure_pip` does.
            venv.ensure_pip(upgrade=install_pip is InstallationChoice.UPGRADED, cwd=cwd)
        if project_upgrades:
            venv.interpreter.execute(
                args=["-m", "pip", "install", "-U"] + project_upgrades, env=env, cwd=cwd
            )
        if project_installs:
            venv.interpreter.execute(
                args=["-m", "pip", "install"] + list(project_installs), env=env, cwd=cwd
            )
        return venv

    @classmethod
    def create_atomic(
        cls,
        venv_dir,  # type: AtomicDirectory
        interpreter=None,  # type: Optional[PythonInterpreter]
        force=False,  # type: bool
        copies=False,  # type: bool
        system_site_packages=False,  # type: bool
        prompt=None,  # type: Optional[str]
        install_pip=InstallationChoice.NO,  # type: InstallationChoice.Value
        install_setuptools=InstallationChoice.NO,  # type: InstallationChoice.Value
        install_wheel=InstallationChoice.NO,  # type: InstallationChoice.Value
        other_installs=(),  # type: Iterable[str]
    ):
        # type: (...) -> Virtualenv
        virtualenv = cls.create(
            venv_dir=venv_dir.work_dir,
            interpreter=interpreter,
            force=force,
            copies=copies,
            system_site_packages=system_site_packages,
            prompt=prompt,
            install_pip=install_pip,
            install_setuptools=install_setuptools,
            install_wheel=install_wheel,
            other_installs=other_installs,
        )
        for script in virtualenv._rewrite_base_scripts(real_venv_dir=venv_dir.target_dir):
            TRACER.log("Re-writing {}".format(script))

        # It's known that PyPy's 7.3.14 releases create venvs with absolute symlinks in bin/ to
        # bin/ local files, which leaves invalid symlinks to the atomic workdir. We fix that up
        # here. See: https://github.com/pypy/pypy/issues/4838
        for path in os.listdir(virtualenv.bin_dir):
            abs_path = os.path.join(virtualenv.bin_dir, path)
            if not os.path.islink(abs_path):
                continue
            link_target = os.readlink(abs_path)
            if not os.path.isabs(link_target):
                continue
            if virtualenv.bin_dir == safe_commonpath((virtualenv.bin_dir, link_target)):
                rel_dst = os.path.relpath(link_target, virtualenv.bin_dir)
                TRACER.log(
                    "Replacing absolute symlink {src} -> {dst} with relative symlink".format(
                        src=abs_path, dst=link_target
                    ),
                    V=3,
                )
                os.unlink(abs_path)
                safe_symlink(rel_dst, abs_path)

        return virtualenv

    def __init__(
        self,
        venv_dir,  # type: str
        python_exe_name="python",  # type: str
        custom_prompt=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        self._venv_dir = venv_dir
        self._custom_prompt = custom_prompt
        self._bin_dir = os.path.join(venv_dir, SCRIPT_DIR)
        python_exe_path = os.path.join(self._bin_dir, script_name(python_exe_name))
        try:
            self._interpreter = PythonInterpreter.from_binary(python_exe_path)
        except PythonInterpreter.Error as e:
            raise InvalidVirtualenvError(
                "The virtualenv at {venv_dir} is not valid. Failed to load an interpreter at "
                "{python_exe_path}: {err}".format(
                    venv_dir=self._venv_dir, python_exe_path=python_exe_path, err=e
                )
            )
        self._site_packages_dir = _find_preferred_site_packages_dir(venv_dir, self._interpreter)
        self._purelib = self._site_packages_dir
        self._platlib = self._site_packages_dir
        for entry in self._interpreter.site_packages:
            if isinstance(entry, Purelib):
                self._purelib = entry.path
            elif isinstance(entry, Platlib):
                self._platlib = entry.path

        self._sys_path = None  # type: Optional[Tuple[str, ...]]

    @property
    def venv_dir(self):
        # type: () -> str
        return self._venv_dir

    @property
    def _pyvenv_cfg(self):
        # type: () -> Optional[PyVenvCfg]
        if not hasattr(self, "__pyvenv_cfg"):
            self.__pyvenv_cfg = PyVenvCfg.find(self._interpreter.binary)
        return self.__pyvenv_cfg

    @property
    def created_by(self):
        # type: () -> str
        if self._pyvenv_cfg:
            version = self._pyvenv_cfg.config("virtualenv", None)
            return "virtualenv {version}".format(version=version) if version else "venv"
        return "unknown"

    @property
    def include_system_site_packages(self):
        # type: () -> Optional[bool]
        return self._pyvenv_cfg.include_system_site_packages if self._pyvenv_cfg else None

    @property
    def custom_prompt(self):
        # type: () -> Optional[str]
        return self._custom_prompt

    def join_path(self, *components):
        # type: (*str) -> str
        return os.path.join(self._venv_dir, *components)

    def bin_path(self, *components):
        # type: (*str) -> str
        return script_name(os.path.join(self._bin_dir, *components))

    @property
    def bin_dir(self):
        # type: () -> str
        return self._bin_dir

    @property
    def site_packages_dir(self):
        # type: () -> str
        return self._site_packages_dir

    @property
    def purelib(self):
        # type: () -> str
        return self._purelib

    @property
    def platlib(self):
        # type: () -> str
        return self._platlib

    @property
    def interpreter(self):
        # type: () -> PythonInterpreter
        return self._interpreter

    def iter_executables(self):
        # type: () -> Iterator[str]
        for path in _iter_files(self._bin_dir):
            if is_exe(path):
                yield path

    @property
    def sys_path(self):
        # type: () -> Tuple[str, ...]
        return self.interpreter.sys_path

    def iter_distributions(self, rescan=False):
        # type: (bool) -> Iterator[Distribution]
        for dist in find_distributions(
            search_path=[entry.path for entry in self._interpreter.site_packages], rescan=rescan
        ):
            yield dist

    def _rewrite_base_scripts(self, real_venv_dir):
        # type: (str) -> Iterator[str]
        scripts = [
            path
            for path in _iter_files(self._bin_dir)
            if _is_python_script(path) or re.search(r"^[Aa]ctivate", os.path.basename(path))
        ]
        if scripts:
            rewritten_files = set()
            with closing(FileInput(files=sorted(scripts), inplace=True)) as fi:
                for line in fi:
                    rewritten_line = line.replace(self._venv_dir, real_venv_dir)
                    if rewritten_line != line:
                        filename = fi.filename()
                        if filename not in rewritten_files:
                            rewritten_files.add(filename)
                            yield filename
                    sys.stdout.write(rewritten_line)

    def rewrite_scripts(
        self,
        python=None,  # type: Optional[str]
        python_args=None,  # type: Optional[str]
    ):
        # type: (...) -> Iterator[str]
        python_scripts = [
            executable for executable in self.iter_executables() if _is_python_script(executable)
        ]
        if python_scripts:
            with closing(FileInput(files=sorted(python_scripts), inplace=True, mode="rb")) as fi:
                # N.B.: `FileInput` is strange, but useful: the context manager above monkey-patches
                # sys.stdout to print to the corresponding original input file, which is has moved
                # aside.
                for line in fi:
                    buffer = get_stdout_bytes_buffer()
                    if fi.isfirstline():
                        shebang = create_shebang(
                            python_exe=python or self._interpreter.binary, python_args=python_args
                        )
                        buffer.write("{shebang}\n".format(shebang=shebang).encode("utf-8"))
                        yield fi.filename()
                    else:
                        # N.B.: These lines include the newline already.
                        buffer.write(cast(bytes, line))

    def ensure_pip(
        self,
        upgrade=False,  # type: bool
        cwd=None,  # type: Optional[str]
    ):
        # type: (...) -> str

        pip_script = self.bin_path("pip")
        if is_exe(pip_script) and not upgrade:
            return pip_script
        try:
            self._interpreter.execute(args=["-m", "ensurepip", "-U", "--default-pip"], cwd=cwd)
        except Executor.NonZeroExit:
            # Early Python 2.7 versions and some system Pythons do not come with ensurepip
            # installed. We fall back to get-pip.py which is available in dedicated versions for
            # Python 2.{6,7} and 3.{2,3,4,5,6} and a single version for anything newer.
            get_pip_script = "get-pip.py"
            major, minor = self._interpreter.version[:2]
            if (major, minor) <= (3, 6):
                version_dir = "{major}.{minor}".format(major=major, minor=minor)
                url_rel_path = "{version_dir}/{script}".format(
                    version_dir=version_dir, script=get_pip_script
                )
                dst_rel_path = os.path.join(version_dir, get_pip_script)
            else:
                url_rel_path = get_pip_script
                dst_rel_path = os.path.join("default", get_pip_script)
            get_pip = os.path.join(ENV.PEX_ROOT, "get-pip", dst_rel_path)
            with atomic_directory(os.path.dirname(get_pip)) as atomic_dir:
                if not atomic_dir.is_finalized():
                    with URLFetcher().get_body_stream(
                        "https://bootstrap.pypa.io/pip/" + url_rel_path
                    ) as src_fp, safe_open(
                        os.path.join(atomic_dir.work_dir, os.path.basename(get_pip)), "wb"
                    ) as dst_fp:
                        shutil.copyfileobj(src_fp, dst_fp)
            self._interpreter.execute(args=[get_pip, "--no-wheel"], cwd=cwd)
        if upgrade:
            self._interpreter.execute(args=["-m", "pip", "install", "-U", "pip"], cwd=cwd)
        return pip_script
