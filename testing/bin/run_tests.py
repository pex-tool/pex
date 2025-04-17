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
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace

import coloredlogs


def find_project_dir():
    # type: () -> str
    start = os.path.dirname(__file__)
    candidate = os.path.realpath(start)
    while True:
        pyproject_toml = os.path.join(candidate, "pyproject.toml")
        if os.path.isfile(pyproject_toml):
            return candidate
        next_candidate = os.path.dirname(candidate)
        if next_candidate == candidate:
            break
        candidate = next_candidate

    sys.exit(
        os.linesep.join(
            (
                "Failed to find the project root searching from directory {start!r}.".format(
                    start=os.path.realpath(start)
                ),
                "No `pyproject.toml` file found at its level or above.",
            )
        )
    )


# Ensure the repo root is on the `sys.path` (for access to the pex and testing packages).
os.environ["_PEX_TEST_PROJECT_DIR"] = find_project_dir()
sys.path.insert(0, os.environ["_PEX_TEST_PROJECT_DIR"])

from pex import windows
from pex.compatibility import urlparse
from pex.fs import safe_rename
from pex.typing import TYPE_CHECKING, cast
from pex.util import named_temporary_file
from testing import devpi, pex_project_dir

if TYPE_CHECKING:
    from typing import Iterator, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class JunitReport(object):
    @staticmethod
    def register_options(parser):
        # type: (ArgumentParser) -> None
        parser.add_argument(
            "--junit-report",
            metavar="PATH",
            help="Produce a junit xml test report at the given path.",
        )
        parser.add_argument(
            "--junit-report-suppress-stdio",
            action="store_true",
            help="Do not include stdout or stderr from tests in the report.",
        )
        parser.add_argument(
            "--junit-report-redact",
            dest="junit_report_redactions",
            action="append",
            default=[],
            help="Add a string to redact from the junit xml test report.",
        )

    @classmethod
    def from_options(cls, options):
        # type: (Namespace) -> Optional[JunitReport]

        if not options.junit_report:
            return None

        return cls(
            path=os.path.realpath(options.junit_report),
            suppress_stdio=options.junit_report_suppress_stdio,
            redactions=tuple(options.junit_report_redactions),
        )

    path = attr.ib()  # type: str
    suppress_stdio = attr.ib()  # type: bool
    redactions = attr.ib()  # type: Tuple[str, ...]

    def iter_pytest_options(self):
        # type: () -> Iterator[str]

        yield "--junit-xml"
        yield self.path
        if self.suppress_stdio:
            yield "-o"
            yield "junit_logging=no"

    def redact(self):
        # type: () -> None

        if not os.path.exists(self.path):
            return

        with open(self.path) as in_fp:
            content = in_fp.read()

        for redaction in self.redactions:
            content = content.replace(redaction, "***")

        with named_temporary_file(
            mode="w", dir=os.path.dirname(self.path), prefix="junit-xml.", suffix=".rewritten"
        ) as out_fp:
            out_fp.write(content)
            out_fp.close()
            safe_rename(out_fp.name, self.path)


def iter_test_control_env_vars():
    # type: () -> Iterator[Tuple[str, str]]
    for var, value in sorted(os.environ.items()):
        if re.search(r"(PEX|PIP|PYTHON)", var):
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
        default="127.0.0.1",
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

    JunitReport.register_options(parser)
    options, passthrough_args = parser.parse_known_args()
    junit_report = JunitReport.from_options(options)

    coloredlogs.install(
        level=options.log_level, fmt="%(levelname)s %(message)s", isatty=options.color
    )
    logger = logging.getLogger(parser.prog)
    logger.log(
        logging.root.level, "Logging configured at level {level}.".format(level=options.log_level)
    )

    # Ensure we have stubs available to alleviate tests from having to distinguish a special loose
    # source state of the Pex codebase vs a packaged state.
    for stub in windows.fetch_all_stubs():
        if not stub.cached:
            logger.info("Fetched windows script executable stub: {stub}".format(stub=stub.path))

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
    logger.info("Test control environment variables:")
    for var, value in test_control_env_vars:
        logger.info("{var}={value}".format(var=var, value=value))

    args = [sys.executable, "-m", "pytest", "-n", "auto"]

    # When run under dev-cmd, FORCE_COLOR=1 is set to propagate auto-detection of a color terminal.
    # This affects a handful of our tests; so we discard and let the --color option below control
    # our own color output.
    # TODO(John Sirois): Work with dev-cmd on this, it seems inappropriate to be using FORCE_COLOR
    #  like this.
    os.environ.pop("FORCE_COLOR", None)
    if options.color:
        args.extend(["--color", "yes"])

    if options.it:
        args.extend(["tests/integration", "-p", "testing.pytest_utils.shard"])
    else:
        args.extend(["tests", "--ignore", "tests/integration"])
    args.extend(passthrough_args or ["-vvs"])

    env = os.environ.copy()
    custom_pex_root = env.pop("PEX_ROOT", None)
    if custom_pex_root is not None:
        # Tests rely on being able to control the PEX_ROOT via --pex-root and --runtime-pex-root,
        # but PEX_ROOT trumps; so we unset if present.
        logger.warning(
            "Unsetting PEX_ROOT={custom_pex_root} for test run.".format(
                custom_pex_root=custom_pex_root
            )
        )

    if junit_report:
        args.extend(junit_report.iter_pytest_options())

    try:
        return subprocess.call(args=args, cwd=pex_project_dir(), env=env)
    finally:
        if junit_report:
            junit_report.redact()


if __name__ == "__main__":
    sys.exit(main())
