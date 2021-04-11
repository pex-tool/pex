# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import re
import subprocess

from pex.common import is_exe
from pex.compatibility import to_unicode
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import Iterator, List, Optional, Text, Tuple
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Pyenv(object):
    root = attr.ib()  # type: Text

    @classmethod
    def find(cls):
        # type: () -> Optional[Pyenv]
        """Finds the active pyenv installation if any."""
        with TRACER.timed("Searching for pyenv root...", V=3):
            pyenv_root = to_unicode(os.environ.get("PYENV_ROOT", ""))
            if not pyenv_root:
                for path_entry in os.environ.get("PATH", "").split(os.pathsep):
                    pyenv_exe = os.path.join(path_entry, "pyenv")
                    if is_exe(pyenv_exe):
                        process = subprocess.Popen(args=[pyenv_exe, "root"], stdout=subprocess.PIPE)
                        stdout, _ = process.communicate()
                        if process.returncode == 0:
                            pyenv_root = stdout.decode("utf-8").strip()
                            break

            if pyenv_root:
                pyenv = cls(pyenv_root)
                TRACER.log("A pyenv installation was found: {}".format(pyenv), V=6)
                return pyenv

            TRACER.log("No pyenv installation was found.", V=6)
            return None

    @attr.s(frozen=True)
    class Shim(object):
        pyenv = attr.ib()  # type: Pyenv
        path = attr.ib()  # type: str
        name = attr.ib()  # type: str
        major = attr.ib()  # type: Optional[str]
        minor = attr.ib()  # type: Optional[str]

        _SHIM_REGEX = re.compile(
            r"""
            ^
            (?P<name>
                python |
                pypy
            )
            (?:
                # Major version
                (?P<major>[2-9])
                (?:
                    \.
                    # Minor version
                    (?P<minor>[0-9])
                    # Some pyenv pythons include a suffix on the interpreter name, similar to
                    # PEP-3149. For example, python3.6m to indicate it was built with pymalloc.
                    [a-z]?
                )?
            )?
            $
            """,
            flags=re.VERBOSE,
        )

        @classmethod
        def parse(cls, pyenv, binary):
            # type: (Pyenv, str) -> Optional[Pyenv.Shim]
            """Parses shim information from a python binary path if it looks like a pyenv shim."""
            if os.path.dirname(binary) != os.path.join(pyenv.root, "shims"):
                return None
            match = cls._SHIM_REGEX.match(os.path.basename(binary))
            if match is None:
                return None
            return cls(
                pyenv=pyenv,
                path=binary,
                name=match.group("name"),
                major=match.group("major"),
                minor=match.group("minor"),
            )

        _PYENV_CPYTHON_VERSION_LEADING_CHARS = frozenset(str(digit) for digit in range(2, 10))

        def select_version(self, search_dir=None):
            # type: (Optional[str]) -> Optional[Text]
            """Reports the active shim version for the given directory or $PWD.

            If the shim is not activated, returns `None`.
            """
            with TRACER.timed("Calculating active version for {}...".format(self), V=6):
                active_versions = self.pyenv.active_versions(search_dir=search_dir)
                if active_versions:
                    if self.name == "python" and not self.major and not self.minor:
                        for pyenv_version in active_versions:
                            if pyenv_version[0] in self._PYENV_CPYTHON_VERSION_LEADING_CHARS:
                                TRACER.log(
                                    "{} has active version {}".format(self, pyenv_version), V=6
                                )
                                return pyenv_version

                    prefix = "{name}{major}{minor}".format(
                        name="" if self.name == "python" else self.name,
                        major=self.major or "",
                        minor=".{}".format(self.minor) if self.minor else "",
                    )
                    for pyenv_version in active_versions:
                        if pyenv_version.startswith(prefix):
                            TRACER.log("{} has active version {}".format(self, pyenv_version), V=6)
                            return pyenv_version

                TRACER.log("{} is not activated.".format(self), V=6)
                return None

    def as_shim(self, binary):
        # type: (str) -> Optional[Shim]
        """View the given binary path as a pyenv shim script if it is one."""
        return self.Shim.parse(self, binary)

    @staticmethod
    def _read_pyenv_versions(version_file):
        # type: (Text) -> Iterator[Text]
        with open(version_file) as fp:
            for line in fp:
                for version in line.strip().split():
                    yield version

    @staticmethod
    def _find_local_version_file(search_dir):
        # type: (str) -> Optional[str]
        while True:
            local_version_file = os.path.join(search_dir, ".python-version")
            if os.path.exists(local_version_file):
                return local_version_file
            parent_dir = os.path.dirname(search_dir)
            if parent_dir == search_dir:
                return None
            search_dir = parent_dir

    def active_versions(self, search_dir=None):
        # type: (Optional[str]) -> Tuple[Text, ...]
        """Reports the active pyenv versions for the given starting search directory or $PWD."""

        # See: https://github.com/pyenv/pyenv#choosing-the-python-version
        with TRACER.timed("Finding {} active versions...".format(self), V=6):
            shell_version = os.environ.get("PYENV_VERSION")
            if shell_version:
                TRACER.log(
                    "Found active pyenv version of PYENV_VERSION={}".format(shell_version), V=6
                )
                return (shell_version,)

            cwd = search_dir if search_dir is not None else os.getcwd()
            TRACER.log("Looking for pyenv version files starting from {}.".format(cwd), V=6)

            versions = []  # type: List[Text]
            local_version = self._find_local_version_file(search_dir=cwd)
            if local_version:
                versions.extend(self._read_pyenv_versions(local_version))
                TRACER.log("Found active versions in {}: {}".format(local_version, versions), V=6)
            else:
                global_version = os.path.join(self.root, "version")
                if os.path.exists(global_version):
                    versions.extend(self._read_pyenv_versions(global_version))
                    TRACER.log(
                        "Found active versions in {}: {}".format(global_version, versions), V=6
                    )

            return tuple(versions)
