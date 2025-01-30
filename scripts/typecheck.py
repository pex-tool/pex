#!/usr/bin/env python3

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from pex.common import safe_mkdtemp


def find_files_to_check(
    include: Iterable[str],
    include_files: Iterable[str] = (),
    exclude: Iterable[str] = (),
    exclude_files: Iterable[str] = (),
) -> Iterator[str]:
    excluded = frozenset(os.path.normpath(e) for e in exclude)
    for root, dirs, files in os.walk(os.curdir):
        if os.path.realpath(root) == os.path.realpath(os.curdir):
            dirs[:] = list(include)
        else:
            dirs[:] = [
                d for d in dirs if os.path.relpath(os.path.join(root, d), os.curdir) not in excluded
            ]

        for f in files:
            if not f.endswith(".py"):
                continue
            if os.path.relpath(os.path.join(root, f), os.curdir) in exclude_files:
                continue
            yield os.path.join(root, f)
    for f in include_files:
        yield f


def run_mypy(python_version: str, files: Sequence[str], subject: str = "files") -> None:
    print(
        f"Typechecking {len(files)} {subject} using Python "
        f"{'.'.join(map(str, sys.version_info[:3]))} against Python {python_version} ..."
    )
    with (Path(safe_mkdtemp()) / "files.txt").open(mode="w") as fp:
        for f in sorted(files):
            print(f, file=fp)
        fp.close()

        subprocess.run(args=["mypy", "--python-version", python_version, f"@{fp.name}"], check=True)


def main() -> None:
    run_mypy(
        "2.7", files=sorted(find_files_to_check(include=["build-backend"])), subject="build-backend"
    )
    run_mypy(
        "3.9",
        files=sorted(find_files_to_check(include=["docs"])),
        subject="sphinx_pex",
    )
    py27_scripts = os.path.join("scripts", "py27")
    run_mypy(
        "2.7",
        files=sorted(find_files_to_check(include=[py27_scripts])),
        subject="Python 2.7 scripts",
    )
    vendor_main = os.path.join("pex", "vendor", "__main__.py")
    run_mypy(
        "3.9",
        files=sorted(
            find_files_to_check(
                include=["package", "scripts"], include_files=[vendor_main], exclude=[py27_scripts]
            )
        ),
        subject="scripts",
    )

    source_and_tests = sorted(
        find_files_to_check(
            include=["pex", "testing", "tests"],
            exclude=[os.path.join("pex", "vendor", "_vendored")],
            exclude_files=[vendor_main],
        )
    )
    for python_version in ("3.13", "3.5", "2.7"):
        run_mypy(python_version, files=source_and_tests)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
