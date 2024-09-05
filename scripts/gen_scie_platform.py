#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import logging
import os.path
import platform
import subprocess
import sys
import tempfile
from argparse import ArgumentError, ArgumentTypeError
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterable, Iterator

logger = logging.getLogger(__name__)


def create_all_complete_platforms(
    _dest_dir: Path,
    *,
    _pbs_release: str,
    _python_version: str,
) -> Iterable[Path]:
    raise NotImplementedError(
        "TODO(John Sirois): Implement triggering the gen-scie-platforms workflow via workflow "
        "dispatch and then gathering the output artifacts to obtain the full suite of complete "
        "platforms needed to generate all the Pex scies."
    )


def current_platform() -> str:
    system = platform.system().lower()
    if system == "darwin":
        system = "macos"
    machine = platform.machine().lower()
    if machine in ("aarch64", "arm64"):
        return f"{system}-aarch64"
    elif machine in ("amd64", "x86_64"):
        return f"{system}-x86_64"
    raise ValueError(f"Unexpected platform.machine(): {platform.machine()}")


@contextmanager
def pex3_binary(*, pbs_release: str, python_version: str) -> Iterator[str]:
    with tempfile.TemporaryDirectory() as td:
        pex3 = os.path.join(td, "pex3")
        subprocess.run(
            args=[
                sys.executable,
                "-m",
                "pex",
                ".",
                "-c",
                "pex3",
                "--scie",
                "lazy",
                "--scie-pbs-release",
                pbs_release,
                "--scie-python-version",
                python_version,
                "-o",
                pex3,
            ],
            check=True,
        )
        yield pex3


def create_complete_platform(
    complete_platform_file: Path,
    *,
    pbs_release: str,
    python_version: str,
    comment: str | None = None
) -> None:
    with pex3_binary(pbs_release=pbs_release, python_version=python_version) as pex3:
        complete_platform = json.loads(
            subprocess.run(
                args=[pex3, "interpreter", "inspect", "--markers", "--tags"],
                stdout=subprocess.PIPE,
                check=True,
            ).stdout
        )
        path = complete_platform.pop("path")
        if comment:
            complete_platform["comment"] = comment
        logger.info(f"Generating {complete_platform_file} using Python at:\n{path}")

        complete_platform_file.parent.mkdir(parents=True, exist_ok=True)
        with complete_platform_file.open("w") as fp:
            json.dump(complete_platform, fp, indent=2, sort_keys=True)


def main(out: IO[str]) -> str | int | None:
    try:
        plat = current_platform()
    except ValueError as e:
        sys.exit((str(e)))

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d", "--dest-dir", type=Path, default=Path("package") / "complete-platforms"
    )
    parser.add_argument("--pbs-release", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    try:
        options = parser.parse_args()
    except (ArgumentError, ArgumentTypeError) as e:
        return str(e)

    logging.basicConfig(level=logging.INFO if options.verbose else logging.WARNING)

    generated_files: list[Path] = []
    if options.all:
        generated_files.extend(
            create_all_complete_platforms(
                _dest_dir=options.dest_dir,
                _pbs_release=options.pbs_release,
                _python_version=options.python_version,
            )
        )
    else:
        complete_platform_file = options.dest_dir / f"{plat}.json"
        try:
            create_complete_platform(
                complete_platform_file=complete_platform_file,
                pbs_release=options.pbs_release,
                python_version=options.python_version,
                comment=(
                    "DO NOT EDIT - Generated via: `tox -e gen-scie-platform -d {dest_dir} "
                    "--pbs-release {pbs_release} --python-version {python_version}`.".format(
                        dest_dir=options.dest_dir,
                        pbs_release=options.pbs_release,
                        python_version=options.python_version,
                    )
                ),
            )
        except subprocess.CalledProcessError as e:
            return str(e)
        generated_files.append(complete_platform_file)

    for file in generated_files:
        print(str(file), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main(out=sys.stdout))
