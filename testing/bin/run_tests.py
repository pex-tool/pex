#!/usr/bin/env python
# Copyright 2023 Pex project contributors.
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

from pex.compatibility import urlparse
from pex.typing import TYPE_CHECKING, cast
from testing import devpi, pex_project_dir

if TYPE_CHECKING:
    from typing import Iterator, Tuple


def iter_test_control_env_vars():
    # type: () -> Iterator[Tuple[str, str]]
    for var, value in sorted(os.environ.items()):
        if re.search(r"(PEX|PIP|PYTHON)", var) and var != "PYTHONHASHSEED":
            yield var, value


def main():
    # type: () -> int
    parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        "-l",
        "--log-level",
        type=lambda arg: arg.upper(),
        default="INFO",
        choices=["DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level (case insensitive).",
    )
    parser.add_argument("--color", default=None, action="store_true", help="Force colored logging.")
    parser.add_argument(
        "--devpi", action="store_true", help="Proxy PyPI through a local devpi server."
    )
    parser.add_argument(
        "--require-devpi",
        action="store_true",
        help=(
            "Fail fast if `--devpi` was requested but the server can't be started or connected to. "
            "Exits with code 42."
        ),
    )
    parser.add_argument(
        "--devpi-host",
        type=str,
        default="0.0.0.0",
        help="The domain/ip address to have the local devpi server listen on.",
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

    coloredlogs.install(
        level=options.log_level, fmt="%(levelname)s %(message)s", isatty=options.color
    )
    logger = logging.getLogger(parser.prog)
    logger.log(
        logging.root.level, "Logging configured at level {level}.".format(level=options.log_level)
    )

    if options.devpi:
        if options.shutdown_devpi:
            atexit.register(devpi.shutdown)
        launch_result = devpi.launch(
            host=options.devpi_host,
            port=options.devpi_port,
            timeout=options.devpi_timeout,
            max_connection_retries=options.devpi_max_connection_retries,
            request_timeout=options.devpi_request_timeout,
        )
        if isinstance(launch_result, devpi.LaunchResult):
            os.environ["_PEX_USE_PIP_CONFIG"] = str(True)
            os.environ["PIP_INDEX_URL"] = launch_result.url
            os.environ["PIP_TRUSTED_HOST"] = cast(
                # We know the local devpi server URL will always have a host and never be None.
                str,
                urlparse.urlparse(launch_result.url).hostname,
            )
            logger.info(
                "Devpi server already running."
                if launch_result.already_running
                else "Launched devpi server."
            )
        else:
            if options.require_devpi:
                logger.critical("Failed to launch devpi server.")
                log_log_level = logging.ERROR
            else:
                logger.warning("Failed to launch devpi server. Continuing without it...")
                log_log_level = logging.DEBUG
            with open(launch_result) as fp:
                for line in fp:
                    logger.log(log_log_level, line.rstrip())
            if options.require_devpi:
                return 42

    test_control_env_vars = list(iter_test_control_env_vars())
    if test_control_env_vars:
        logger.info("Test control environment variables:")
        for var, value in test_control_env_vars:
            logger.info("{var}={value}".format(var=var, value=value))
    else:
        logger.info("No test control environment variables set.")

    args = [sys.executable, "-m", "pytest", "-n", "auto"]
    if options.it:
        args.extend(["tests/integration", "-p", "testing.pytest.shard"])
    else:
        args.extend(["tests", "--ignore", "tests/integration"])
    args.extend(passthrough_args or ["-vvs"])

    return subprocess.call(args=args, cwd=pex_project_dir())


if __name__ == "__main__":
    sys.exit(main())
