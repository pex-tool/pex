# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import logging
import os
import pkgutil
import re
import shutil
import sys
from contextlib import closing
from fileinput import FileInput
from textwrap import dedent

from pex.atomic_directory import AtomicDirectory, atomic_directory
from pex.common import is_exe, safe_mkdir, safe_open
from pex.compatibility import commonpath, get_stdout_bytes_buffer
from pex.dist_metadata import Distribution, find_distributions
from pex.executor import Executor
from pex.fetcher import URLFetcher
from pex.interpreter import PythonInterpreter, PyVenvCfg
from pex.orderedset import OrderedSet
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.util import named_temporary_file
from pex.variables import ENV
from pex.version import __version__

if TYPE_CHECKING:
    from typing import Iterator, Optional, Tuple, Union


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
            # See: https://www.python.org/dev/peps/pep-0427/#recommended-installer-features
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


def find_site_packages_dir(
    venv_dir,  # type: str
    interpreter=None,  # type: Optional[PythonInterpreter]
):
    # type: (...) -> str

    real_venv_dir = os.path.realpath(venv_dir)
    site_packages_dirs = OrderedSet()  # type: OrderedSet[str]

    interpreter = interpreter or PythonInterpreter.get()
    for entry in interpreter.sys_path:
        real_entry_path = os.path.realpath(entry)
        if commonpath((real_venv_dir, real_entry_path)) != real_venv_dir:
            # This ignores system site packages when the venv is built with --system-site-packages.
            continue
        if "site-packages" == os.path.basename(real_entry_path) and os.path.isdir(real_entry_path):
            site_packages_dirs.add(real_entry_path)

    if not site_packages_dirs:
        raise InvalidVirtualenvError(
            "The virtualenv at {venv_dir} is not valid. No site-packages directory was found in "
            "its sys.path:\n{sys_path}".format(
                venv_dir=venv_dir, sys_path="\n".join(interpreter.sys_path)
            )
        )
    if len(site_packages_dirs) > 1:
        raise InvalidVirtualenvError(
            "The virtualenv at {venv_dir} is not valid. It has more than one site-packages "
            "directory:\n{site_packages}".format(
                venv_dir=venv_dir, site_packages="\n".join(site_packages_dirs)
            )
        )
    return site_packages_dirs.pop()


class Virtualenv(object):
    VIRTUALENV_VERSION = "16.7.12"

    @classmethod
    def enclosing(cls, python):
        # type: (Union[str, PythonInterpreter]) -> Optional[Virtualenv]
        """Return the virtual environment the given python interpreter is enclosed in."""
        interpreter = (
            python
            if isinstance(python, PythonInterpreter)
            else PythonInterpreter.from_binary(python)
        )
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
    ):
        # type: (...) -> Virtualenv
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

        # Guard against API calls from environment with ambient PYTHONPATH preventing pip virtualenv
        # creation. See: https://github.com/pantsbuild/pex/issues/1451
        env = os.environ.copy()
        pythonpath = env.pop("PYTHONPATH", None)
        if pythonpath:
            TRACER.log(
                "Scrubbed PYTHONPATH={} from the virtualenv creation environment.".format(
                    pythonpath
                ),
                V=3,
            )

        custom_prompt = None  # type: Optional[str]
        py_major_minor = interpreter.version[:2]
        if py_major_minor[0] == 2 or (
            interpreter.identity.interpreter == "PyPy" and py_major_minor[:2] <= (3, 7)
        ):
            # N.B.: PyPy3.6 and PyPy3.7 come equipped with a venv module but it does not seem to
            # work.
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
                interpreter.execute(args=args, env=env)
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
            args = ["-m", "venv", "--without-pip", venv_dir]
            if copies:
                args.append("--copies")
            if system_site_packages:
                args.append("--system-site-packages")
            if prompt and py_major_minor >= (3, 6):
                args.extend(["--prompt", prompt])
                custom_prompt = prompt
            interpreter.execute(args=args, env=env)

        return cls(venv_dir, custom_prompt=custom_prompt)

    @classmethod
    def create_atomic(
        cls,
        venv_dir,  # type: AtomicDirectory
        interpreter=None,  # type: Optional[PythonInterpreter]
        force=False,  # type: bool
        copies=False,  # type: bool
        prompt=None,  # type: Optional[str]
    ):
        # type: (...) -> Virtualenv
        virtualenv = cls.create(
            venv_dir=venv_dir.work_dir,
            interpreter=interpreter,
            force=force,
            copies=copies,
            prompt=prompt,
        )
        for script in virtualenv._rewrite_base_scripts(real_venv_dir=venv_dir.target_dir):
            TRACER.log("Re-writing {}".format(script))
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
        self._bin_dir = os.path.join(venv_dir, "bin")
        python_exe_path = os.path.join(self._bin_dir, python_exe_name)
        try:
            self._interpreter = PythonInterpreter.from_binary(python_exe_path)
        except PythonInterpreter.InterpreterNotFound as e:
            raise InvalidVirtualenvError(
                "The virtualenv at {venv_dir} is not valid. Failed to load an interpreter at "
                "{python_exe_path}: {err}".format(
                    venv_dir=self._venv_dir, python_exe_path=python_exe_path, err=e
                )
            )
        self._site_packages_dir = find_site_packages_dir(venv_dir, self._interpreter)
        self._base_bin = frozenset(_iter_files(self._bin_dir))
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
        return os.path.join(self._bin_dir, *components)

    @property
    def bin_dir(self):
        # type: () -> str
        return self._bin_dir

    @property
    def site_packages_dir(self):
        # type: () -> str
        return self._site_packages_dir

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
        if self._sys_path is None:
            _, stdout, _ = self.interpreter.execute(
                args=["-c", "import os, sys; print(os.linesep.join(sys.path))"]
            )
            self._sys_path = tuple(stdout.strip().splitlines())
        return self._sys_path

    def iter_distributions(self):
        # type: () -> Iterator[Distribution]
        """"""
        for dist in find_distributions(search_path=self.sys_path):
            yield dist

    def _rewrite_base_scripts(self, real_venv_dir):
        # type: (str) -> Iterator[str]
        scripts = [
            path
            for path in self._base_bin
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
                        shebang = [python or self._interpreter.binary]
                        if python_args:
                            shebang.append(python_args)
                        buffer.write(
                            "#!{shebang}\n".format(shebang=" ".join(shebang)).encode("utf-8")
                        )
                        yield fi.filename()
                    else:
                        # N.B.: These lines include the newline already.
                        buffer.write(cast(bytes, line))

    def install_pip(self, upgrade=False):
        # type: (bool) -> str
        try:
            self._interpreter.execute(args=["-m", "ensurepip", "-U", "--default-pip"])
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
            self._interpreter.execute(args=[get_pip, "--no-wheel"])
        if upgrade:
            self._interpreter.execute(args=["-m", "pip", "install", "-U", "pip"])
        return self.bin_path("pip")
