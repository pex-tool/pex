#!/usr/bin/env python
# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import atexit
import logging
import os
import re
import subprocess
import sys
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser

import coloredlogs

# Ensure the repo root is on the `sys.path` (for access to the pex and testing packages).
os.environ["_PEX_TEST_PROJECT_DIR"] = str(
    subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode("ascii").strip()
)
sys.path.insert(0, os.environ["_PEX_TEST_PROJECT_DIR"])

from pex.typing import TYPE_CHECKING
from testing import devpi, pex_project_dir

if TYPE_CHECKING:
    from typing import Iterator, Tuple


def iter_test_control_env_vars():
    # type: () -> Iterator[Tuple[str, str]]
    for var, value in sorted(os.environ.items()):
        if re.search(r"(PEX|PYTHON)", var) and var != "PYTHONHASHSEED":
            yield var, value


def main():
    # type: () -> int
    parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument("--color", default=None, action="store_true", help="Force colored logging.")
    parser.add_argument(
        "--devpi", action="store_true", help="Proxy PyPI through a local devpi server."
    )
    parser.add_argument(
        "--devpi-port", type=int, default=0, help="The port to bind the local devpi server to."
    )
    parser.add_argument(
        "--devpi-timeout",
        type=float,
        default=5.0,
        help=(
            "The maximum amount of time (in seconds) to wait for devpi server to start before "
            "continuing without it."
        ),
    )
    parser.add_argument(
        "--devpi-max-connection-retries",
        type=int,
        default=3,
        help="The maximum number of PyPI connection attempt retries.",
    )
    parser.add_argument(
        "--devpi-request-timeout",
        type=int,
        default=5,
        help=(
            "The maximum amount of time to wait (in seconds) for request activity before "
            "terminating the request."
        ),
    )
    parser.add_argument(
        "--shutdown-devpi",
        action="store_true",
        help="If using a devpi server for the run, shut it down at the end of the run.",
    )
    parser.add_argument("--it", action="store_true", help="Restrict scope to integration tests.")
    options, passthrough_args = parser.parse_known_args()

    coloredlogs.install(level="INFO", fmt="%(levelname)s %(message)s", isatty=options.color)
    logger = logging.getLogger(parser.prog)

    if options.devpi:
        if options.shutdown_devpi:
            atexit.register(devpi.shutdown)
        launch_result = devpi.launch(
            port=options.devpi_port,
            timeout=options.devpi_timeout,
            max_connection_retries=options.devpi_max_connection_retries,
            request_timeout=options.devpi_request_timeout,
        )
        if not launch_result:
            logger.warning("Failed to launch devpi server. Continuing without it...")
        else:
            os.environ["_PEX_TEST_DEFAULT_INDEX"] = launch_result.url
            logger.info(
                "Devpi server already running."
                if launch_result.already_running
                else "Launched devpi server."
            )

    test_control_env_vars = list(iter_test_control_env_vars())
    if test_control_env_vars:
        logger.info("Test control environment variables:")
        for var, value in test_control_env_vars:
            logger.info("{var}={value}".format(var=var, value=value))
    else:
        logger.info("No test control environment variables set.")

    if options.it:
        pytest_args = ["-n", "auto", "tests/integration"]
    else:
        pytest_args = ["tests", "--ignore", "tests/integration"]

    return subprocess.call(
        args=[sys.executable, "-m", "pytest"] + pytest_args + passthrough_args or ["-vvs"],
        cwd=pex_project_dir(),
    )


if __name__ == "__main__":
    sys.exit(main())
