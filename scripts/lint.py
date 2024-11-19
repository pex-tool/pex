#!/usr/bin/env python3

import argparse
import subprocess
import sys


def run_autoflake(*args: str) -> None:
    excludes = [
        # The `pex.compatibility` module contains funky conditional symbol export code based on the
        # Python version that trips up autoflake / pyflakes; so we omit the file in its entirety
        # instead of littering it with 10s of `# noqa`.
        "pex/compatibility.py",
        "pex/vendor/_vendored",
    ]
    subprocess.run(
        args=[
            "autoflake",
            *args,
            "--remove-all-unused-imports",
            "--remove-unused-variables",
            "--remove-rhs-for-unused-variables",
            "--in-place",
            "--exclude",
            ",".join(excludes),
            "--recursive",
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
        run_autoflake("--check-diff", "--quiet")
    else:
        run_autoflake()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    try:
        main(check=options.check)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
