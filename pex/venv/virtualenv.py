# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import fileinput
import json
import logging
import os
import re
import sys
from contextlib import closing
from textwrap import dedent

from pex import third_party
from pex.common import AtomicDirectory, is_exe, safe_mkdir
from pex.compatibility import get_stdout_bytes_buffer
from pex.interpreter import PythonInterpreter
from pex.third_party.pkg_resources import resource_string
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.util import named_temporary_file

if TYPE_CHECKING:
    from typing import Iterator, Optional, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr

_MIN_PIP_PYTHON_VERSION = (2, 7, 9)


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


@attr.s(frozen=True)
class DistributionInfo(object):
    project_name = attr.ib()  # type: str
    version = attr.ib()  # type: str
    sys_path_entry = attr.ib()  # type: str


class Virtualenv(object):
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
        if py_major_minor[0] >= 3 and not interpreter.identity.interpreter == "PyPy":
            # N.B.: PyPy3 comes equipped with a venv module but it does not seem to work.
            args = ["-m", "venv", "--without-pip", venv_dir]
            if copies:
                args.append("--copies")
            if prompt and py_major_minor >= (3, 6):
                args.extend(["--prompt", prompt])
                custom_prompt = prompt
            interpreter.execute(args=args, env=env)
        else:
            virtualenv_py = resource_string(__name__, "virtualenv_16.7.12_py")
            with named_temporary_file(mode="wb") as fp:
                fp.write(virtualenv_py)
                fp.close()
                args = [fp.name, "--no-pip", "--no-setuptools", "--no-wheel", venv_dir]
                if copies:
                    args.append("--always-copy")
                if prompt:
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
        self._site_packages_dir = (
            os.path.join(venv_dir, "site-packages")
            if self._interpreter.identity.interpreter == "PyPy"
            else os.path.join(
                venv_dir,
                "lib",
                "python{major_minor}".format(
                    major_minor=".".join(map(str, self._interpreter.version[:2]))
                ),
                "site-packages",
            )
        )
        if not os.path.isdir(self._site_packages_dir):
            raise InvalidVirtualenvError(
                "The virtualenv at {venv_dir} is not valid. The expected site-packages directory "
                "at {site_packages_dir} does not exist.".format(
                    venv_dir=venv_dir, site_packages_dir=self._site_packages_dir
                )
            )
        self._base_bin = frozenset(_iter_files(self._bin_dir))

    @property
    def venv_dir(self):
        # type: () -> str
        return self._venv_dir

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

    def iter_distributions(self):
        # type: () -> Iterator[DistributionInfo]
        """"""
        setuptools_path = tuple(third_party.expose(["setuptools"]))
        _, stdout, _ = self.interpreter.execute(
            args=[
                "-c",
                dedent(
                    """\
                    from __future__ import print_function

                    import sys

                    setuptools_path = {setuptools_path!r}
                    sys.path.extend(setuptools_path)

                    import json
                    from pkg_resources import working_set

                    json.dump(
                        [
                            dict(
                                project_name=dist.project_name,
                                version=dist.version,
                                sys_path_entry=dist.location,
                            ) for dist in working_set if dist.location not in setuptools_path
                        ],
                        sys.stdout,
                    )
                    """.format(
                        setuptools_path=setuptools_path
                    )
                ),
            ],
        )
        for dist_info in json.loads(stdout):
            yield DistributionInfo(**dist_info)

    def _rewrite_base_scripts(self, real_venv_dir):
        # type: (str) -> Iterator[str]
        scripts = [
            path
            for path in self._base_bin
            if _is_python_script(path) or re.search(r"^[Aa]ctivate", os.path.basename(path))
        ]
        if scripts:
            rewritten_files = set()
            with closing(fileinput.input(files=sorted(scripts), inplace=True)) as fi:
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
            with closing(
                fileinput.input(files=sorted(python_scripts), inplace=True, mode="rb")
            ) as fi:
                # N.B.: `fileinput` is strange, but useful: the context manager above monkey-patches
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

    def install_pip(self):
        # type: () -> str
        if self._interpreter.version < _MIN_PIP_PYTHON_VERSION:
            raise PipUnavailableError(
                (
                    "Pip can only be installed for Python>={min_version}, but the current "
                    "interpreter is {interpreter} {version}."
                ).format(
                    min_version=".".join(map(str, _MIN_PIP_PYTHON_VERSION)),
                    interpreter=self._interpreter.identity.interpreter,
                    version=self._interpreter.identity.version_str,
                ),
            )
        self._interpreter.execute(args=["-m", "ensurepip", "-U", "--default-pip"])
        return self.bin_path("pip")
