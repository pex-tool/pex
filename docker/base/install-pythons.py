# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# /// script
# requires-python = ">=3.9"
# ///

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

# N.B.: 3.12 is the default system python for ubuntu 24.04 and software-properties-common uses it.
# There may be a way to substitute the deadsnakes version but I have not found it; so we uninstall
# via `apt autoremove` and let pyenv install a 3.12.

# See: https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa
@dataclass(frozen=True)
class DeadSnake:
    precise_version: str
    packages: list[str]

    def iter_packages(self) -> Iterator[str]:
        version = ".".join(self.precise_version.split(".")[:2])
        for package in self.packages:
            yield f"python{version}-{package}={self.precise_version}*"


# N.B.: 2.7, 3.9 and 3.11 are needed in both version sets to run certain dev-cmd commands.

NEW_DEFAULT_PYTHON = "python3.14"
NEW_VERSIONS = (
    # N.B.: Old, but needed for some dev-cmd commands.
    "2.7.18",
    DeadSnake("3.9.25", ["dev", "venv", "distutils"]),
    # New:
    DeadSnake("3.10.20", ["dev", "venv", "distutils"]),
    DeadSnake("3.11.15", ["dev", "venv"]),
    "3.12.13",
    DeadSnake("3.13.13", ["dev", "venv"]),
    DeadSnake("3.14.5", ["dev", "venv"]),
    DeadSnake("3.15.0~b2", ["dev", "venv"]),
    "pypy3.11-7.3.22",
)

OLD_DEFAULT_PYTHON = "python3.9"
OLD_VERSIONS = (
    # N.B.: New, but needed for some dev-cmd commands.
    "3.11.15",
    # Old:
    "2.7.18",
    "3.5.10",
    "3.6.15",
    "3.7.17",
    "3.8.20",
    "3.9.25",
    "pypy2.7-7.3.22",
    # This is served from:
    #   https://bitbucket-archive.softwareheritage.org/static/14/140b7b14-aa94-424e-b191-9cd3438381f7/attachments/pypy3.5-7.0.0-linux_x86_64-portable.tar.bz2
    # which has begun to prove flaky; so we comment out for now and perhaps need to drop or
    # self-host:
    # pypy3.5-7.0.0
    # This is failing install for unknown reasons:
    # pypy3.6-7.3.3
    "pypy3.7-7.3.9",
    "pypy3.8-7.3.11",
    "pypy3.9-7.3.16",
    "pypy3.10-7.3.19",
)


def install_deadsnakes_versions(
    versions: Iterable[DeadSnake], uninstall: Iterable[str] = ()
) -> None:
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    if versions:
        subprocess.run(
            args=["add-apt-repository", "--yes", "--ppa", "deadsnakes"], env=env, check=True
        )

        packages = [package for dead_snake in versions for package in dead_snake.iter_packages()]
        subprocess.run(args=["apt", "install", "--yes", *packages], env=env, check=True)

        subprocess.run(
            args=["add-apt-repository", "--yes", "--remove", "--ppa", "deadsnakes"],
            env=env,
            check=True,
        )

    subprocess.run(
        args=["apt", "remove", "--yes", "software-properties-common", *uninstall],
        env=env,
        check=True,
    )
    subprocess.run(args=["apt", "autoremove", "--yes"], env=env, check=True)


PYENV_ROOT = Path("/pyenv")
PYENV_REPO = os.environ.get("PYENV_REPO", "https://github.com/pyenv/pyenv")
PYENV_SHA = os.environ.get("PYENV_SHA", "HEAD")
PYENV_ENV = {**os.environ, "PYENV_ROOT": str(PYENV_ROOT)}


def install_pyenv() -> None:
    subprocess.run(args=["git", "clone", "--depth", "1", PYENV_REPO, PYENV_ROOT], check=True)
    subprocess.run(args=["git", "checkout", PYENV_SHA], cwd=PYENV_ROOT, check=True)
    subprocess.run(args=["src/configure"], env=PYENV_ENV, cwd=PYENV_ROOT, check=True)
    subprocess.run(args=["make", "-C", "src"], env=PYENV_ENV, cwd=PYENV_ROOT, check=True)


def install_pyenv_versions(versions: Iterable[str]) -> None:
    if not versions:
        return

    install_pyenv()
    subprocess.run(
        args=[PYENV_ROOT / "bin" / "pyenv", "install", "--force", *versions],
        env=PYENV_ENV,
        check=True,
    )
    for version in versions:
        if version.startswith("pypy"):
            exe = version.split("-")[0]
        else:
            major, minor = version.split(".")[:2]
            exe = f"python{major}.{minor}"
        exe_path = PYENV_ROOT / "versions" / version / "bin" / exe
        if not exe_path.is_file() or not os.access(exe_path, os.R_OK | os.X_OK):
            raise InstallError(
                f"For pyenv version {version}, expected Python exe path does not exist:\n"
                f"  {exe_path}"
            )
        os.symlink(exe_path, f"/usr/bin/{exe}")


def install_pythons(new: bool = True) -> None:
    uninstall: list[str] = []
    versions: Iterable[DeadSnake | str]
    if new:
        # N.B.: Ubuntu 24.04 which ships its own (older) CPython 3.12.
        uninstall.append("python3.12")
        versions = NEW_VERSIONS
        default_python_exe_name = NEW_DEFAULT_PYTHON
    else:
        # N.B.: Ubuntu 20.04 which ships its own (older) CPython 3.8.
        uninstall.append("python3.8")
        versions = OLD_VERSIONS
        default_python_exe_name = OLD_DEFAULT_PYTHON

    install_deadsnakes_versions(
        versions=[version for version in versions if isinstance(version, DeadSnake)],
        uninstall=uninstall,
    )
    install_pyenv_versions(versions=[version for version in versions if isinstance(version, str)])

    default_python = shutil.which(default_python_exe_name)
    if default_python is None:
        raise InstallError(f"Expected default Python {default_python_exe_name} does not exist")
    os.symlink(default_python, "/usr/bin/python")


class InstallError(Exception):
    pass


def main() -> Any:
    args_parser = ArgumentParser()
    args_parser.add_argument("--pythons", choices=["old", "new"], default="new")
    args = args_parser.parse_args()

    install_pythons(new=args.pythons == "new")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except InstallError as e:
        sys.exit(str(e))
