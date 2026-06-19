# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# /// script
# requires-python = "==3.11.*"
# ///

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

import tomllib


def parse_str_field(subject: str, name: str, data: dict[str, Any]) -> str:
    try:
        value = data.pop(name)
    except KeyError:
        raise InstallError(f"A {subject} must define a `{name}` field.")
    if not isinstance(value, str):
        raise InstallError(
            f"The `{name}` field must be a string; given {value} of type {type(value)}."
        )
    return value


def parse_list_field(subject: str, name: str, data: dict[str, Any]) -> list[Any]:
    try:
        values = data.pop(name)
    except KeyError:
        raise InstallError(f"A {subject} must define a `{name}` field.")
    if not isinstance(values, list):
        raise InstallError(
            f"The `{name}` field must be a list; given {values} of type {type(values)}."
        )
    return values


def parse_str_list_field(subject: str, name: str, data: dict[str, Any]) -> list[str]:
    values = parse_list_field(subject, name, data)
    if not all(isinstance(value, str) for value in values):
        raise InstallError(
            f"The `{name}` field must be a list of strings; given {values} which contains "
            f"non-strings."
        )
    return values


# See: https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa
@dataclass(frozen=True)
class DeadSnake:
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeadSnake:
        subject = "Dead Snakes version"
        version = parse_str_field(subject=subject, name="version", data=data)
        packages = parse_str_list_field(subject=subject, name="packages", data=data)
        if data:
            raise InstallError(f"Unrecognized Dead Snakes fields: {', '.join(data.keys())}")
        return cls(precise_version=version, packages=packages)

    precise_version: str
    packages: list[str]

    def iter_packages(self) -> Iterator[str]:
        version = ".".join(self.precise_version.split(".")[:2])
        for package in self.packages:
            yield f"python{version}-{package}={self.precise_version}*"


def install_deadsnakes_versions(
    dead_snakes: Iterable[DeadSnake], uninstall: Iterable[str] = ()
) -> None:
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    if dead_snakes:
        subprocess.run(
            args=["add-apt-repository", "--yes", "ppa:deadsnakes/ppa"], env=env, check=True
        )

        packages = [package for dead_snake in dead_snakes for package in dead_snake.iter_packages()]
        subprocess.run(args=["apt", "install", "--yes", *packages], env=env, check=True)

        subprocess.run(
            args=["add-apt-repository", "--yes", "--remove", "ppa:deadsnakes/ppa"],
            env=env,
            check=True,
        )

    subprocess.run(
        args=["apt", "remove", "--yes", "software-properties-common", *uninstall],
        env=env,
        check=True,
    )
    subprocess.run(args=["apt", "autoremove", "--yes"], env=env, check=True)


# See: https://github.com/pyenv/pyenv
PYENV_ROOT = Path("/pyenv")
PYENV_REPO = os.environ.get("PYENV_REPO", "https://github.com/pyenv/pyenv")
PYENV_SHA = os.environ.get("PYENV_SHA", "HEAD")
PYENV_ENV = {**os.environ, "PYENV_ROOT": str(PYENV_ROOT)}


@dataclass(frozen=True)
class Pyenv:
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Pyenv:
        version = parse_str_field(subject="Pyenv version", name="version", data=data)
        if data:
            raise InstallError(f"Unrecognized pyenv fields: {', '.join(data.keys())}")
        return cls(version=version)

    version: str
    exe: str = field(init=False)
    exe_path: Path = field(init=False)

    def __post_init__(self):
        if self.version.startswith("pypy"):
            exe = self.version.split("-")[0]
        else:
            major, minor = self.version.split(".")[:2]
            exe = f"python{major}.{minor}"
        object.__setattr__(self, "exe", exe)
        object.__setattr__(self, "exe_path", PYENV_ROOT / "versions" / self.version / "bin" / exe)


def install_pyenv() -> None:
    subprocess.run(args=["git", "clone", "--depth", "1", PYENV_REPO, PYENV_ROOT], check=True)
    subprocess.run(args=["git", "checkout", PYENV_SHA], cwd=PYENV_ROOT, check=True)
    subprocess.run(args=["src/configure"], env=PYENV_ENV, cwd=PYENV_ROOT, check=True)
    subprocess.run(args=["make", "-C", "src"], env=PYENV_ENV, cwd=PYENV_ROOT, check=True)


def install_pyenv_versions(pyenvs: Iterable[Pyenv]) -> None:
    if not pyenvs:
        return

    install_pyenv()
    subprocess.run(
        args=[
            PYENV_ROOT / "bin" / "pyenv",
            "install",
            "--force",
            *(pyenv.version for pyenv in pyenvs),
        ],
        env=PYENV_ENV,
        check=True,
    )
    for pyenv in pyenvs:
        if not pyenv.exe_path.is_file() or not os.access(pyenv.exe_path, os.R_OK | os.X_OK):
            raise InstallError(
                f"For pyenv version {pyenv.version}, expected Python exe path does not exist:\n"
                f"  {pyenv.exe_path}"
            )
        os.symlink(pyenv.exe_path, f"/usr/bin/{pyenv.exe}")


@dataclass(frozen=True)
class Versions:
    @classmethod
    def parse(cls, versions_file: Path) -> Versions:
        with versions_file.open(mode="rb") as fp:
            data = tomllib.load(fp)

        subject = "Versions config file"
        default_python_exe_name = parse_str_field(
            subject=subject, name="default-version", data=data
        )
        pyenv_versions: list[Pyenv] = []
        deadsnakes_versions: list[DeadSnake] = []
        for index, version in enumerate(
            parse_list_field(subject=subject, name="versions", data=data)
        ):
            if not isinstance(version, dict):
                raise InstallError(
                    f"The `versions` field must be a list of tables; "
                    f"item {index} is {version} of type {type(version)}."
                )
            match parse_str_field(
                subject=f"{subject} `versions` field item {index}", name="source", data=version
            ):
                case "dead-snakes":
                    try:
                        deadsnakes_versions.append(DeadSnake.from_dict(version))
                    except InstallError as e:
                        raise InstallError(
                            f"Invalid `versions` field dead-snakes item {index}: {e}"
                        )
                case "pyenv":
                    try:
                        pyenv_versions.append(Pyenv.from_dict(version))
                    except InstallError as e:
                        raise InstallError(f"Invalid `versions` field pyenv item {index}: {e}")
                case other:
                    raise InstallError(
                        f"The `versions` field item {index} has unrecognized source of '{other}'; "
                        f"must be either 'dead-snakes' or 'pyenv'."
                    )
        uninstall_packages = parse_str_list_field(
            subject=subject, name="uninstall-packages", data=data
        )
        return cls(
            default_python_exe_name=default_python_exe_name,
            deadsnakes_versions=tuple(deadsnakes_versions),
            pyenv_versions=tuple(pyenv_versions),
            uninstall_packages=tuple(uninstall_packages),
        )

    default_python_exe_name: str
    deadsnakes_versions: tuple[DeadSnake, ...]
    pyenv_versions: tuple[Pyenv, ...]
    uninstall_packages: tuple[str, ...]


def install_pythons(versions: Versions) -> None:
    install_deadsnakes_versions(versions.deadsnakes_versions, uninstall=versions.uninstall_packages)
    install_pyenv_versions(versions.pyenv_versions)

    default_python = shutil.which(versions.default_python_exe_name)
    if default_python is None:
        raise InstallError(
            f"Expected default Python {versions.default_python_exe_name} does not exist"
        )
    os.symlink(default_python, "/usr/bin/python")


class InstallError(Exception):
    pass


def main() -> Any:
    if len(sys.argv) != 2:
        raise InstallError(f"Usage: {sys.argv[0]} <versions config file>")
    versions = Versions.parse(Path(sys.argv[1]))
    install_pythons(versions)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except InstallError as e:
        sys.exit(str(e))
