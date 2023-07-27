#!/usr/bin/env python
# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import os
import re
import subprocess
import sys
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser

# Ensure the repo root is on the `sys.path` (for access to the pex and testing packages).
os.environ["_PEX_TEST_PROJECT_DIR"] = str(
    subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode("ascii").strip()
)
sys.path.insert(0, os.environ["_PEX_TEST_PROJECT_DIR"])

from testing import pex_project_dir


def typechecking():
    # type: () -> bool
    try:
        import typing

        return typing.TYPE_CHECKING
    except ImportError:
        return False


if typechecking():
    from typing import Iterator, Tuple


def iter_test_control_env_vars():
    # type: () -> Iterator[Tuple[str, str]]
    for var, value in sorted(os.environ.items()):
        if re.search(r"(PEX|PYTHON)", var) and var != "PYTHONHASHSEED":
            yield var, value


def main():
    # type: () -> int
    parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        "--",
        dest="passthrough_args",
        metavar="ARG",
        nargs="*",
        help="All arguments following -- are passed to pytest.",
    )
    options, passthrough_args = parser.parse_known_args()

    # The "--" add_argument incantation above is a hack to get argparse to support -- ... style pass
    # through args. In combination with parse_known_args we get a good help string, but
    # options.passthrough_args is _not_ populated. Instead, passthrough_args contains ["--", ...]
    # or []; so we slice off the 1st passthrough arg, which is "--".
    passthrough_args = passthrough_args[1:]

    test_control_env_vars = list(iter_test_control_env_vars())
    if test_control_env_vars:
        print("Test control environment variables:")
        for var, value in test_control_env_vars:
            print("{var}={value}".format(var=var, value=value))
    else:
        print("No test control environment variables set.")

    return subprocess.call(
        args=[sys.executable, "-m", "pytest"] + passthrough_args, cwd=pex_project_dir()
    )


if __name__ == "__main__":
    sys.exit(main())
