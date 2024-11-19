#!/usr/bin/env python3

import argparse
import os
import re
import subprocess
import sys
import threading
from contextlib import contextmanager
from typing import Iterator, TextIO


@contextmanager
def filtered_stream(exclude: str, dest: TextIO) -> Iterator[int]:
    read_fd, write_fd = os.pipe()

    def filter_stream() -> None:
        with os.fdopen(read_fd, "r") as fh:
            for line in fh:
                if not re.search(exclude, line):
                    dest.write(line)

    thread = threading.Thread(target=filter_stream, daemon=True)
    thread.start()
    try:
        yield write_fd
    finally:
        os.close(write_fd)
        thread.join()


def run_black(*args: str) -> None:
    with filtered_stream(
        exclude=r"DEPRECATION: Python 2 support will be removed in the first stable release",
        dest=sys.stdout,
    ) as out_fd:
        subprocess.run(
            args=[
                "black",
                "--color",
                *args,
                "build-backend",
                "docs",
                "package",
                "pex",
                "scripts",
                "setup.py",
                "testing",
                "tests",
            ],
            stdout=out_fd,
            stderr=subprocess.STDOUT,
            check=True,
        )


def run_isort(*args: str) -> None:
    subprocess.run(
        args=[
            "isort",
            *args,
            "build-backend",
            "docs",
            "package",
            "pex",
            "scripts",
            "setup.py",
            "testing",
            "tests",
        ],
        check=True,
    )


def main(check: bool = False) -> None:
    if check:
        run_black("--check")
        run_isort("--check-only")
    else:
        run_black()
        run_isort()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    try:
        main(check=options.check)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
