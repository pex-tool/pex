#!/usr/bin/env python
# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import atexit
import json
import logging
import os
import re
import subprocess
import sys
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace
from logging import Logger
from subprocess import CalledProcessError
from textwrap import dedent

import coloredlogs
import dateutil.parser  # type: ignore[import]  # MyPy can't see the types under Python 2.7.

from pex.common import temporary_dir
from pex.dist_metadata import DistMetadata
from pex.fetcher import URLFetcher
from pex.pep_440 import Version
from pex.requirements import VCSRequirement, parse_requirement_string
from pex.third_party.packaging.specifiers import SpecifierSet


class RunError(Exception):
    pass


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

    raise RunError(
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

from pex import toml, windows
from pex.compatibility import to_unicode, urlparse
from pex.fs import safe_rename
from pex.typing import TYPE_CHECKING, cast
from pex.util import named_temporary_file
from testing import devpi, pex_dist, pex_project_dir

if TYPE_CHECKING:
    from typing import Iterator, List, Optional, Text, Tuple

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
            redactions=tuple(
                redaction
                for redaction in options.junit_report_redactions
                # N.B.: Skip the empty string - there is nothing to redact. We can get these when
                # redactions come from sensitive env vars that are not set in the current
                # environment, for example.
                if redaction
            ),
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


PIP_REPO = "pypa/pip"
PIP_BRANCH = "main"
PIP_WORKFLOW = "CI"


def resolve_pip_dev(logger):
    # type: (Logger) -> Tuple[Version, Optional[SpecifierSet], List[str], str]

    build_system_requires = []  # type: List[str]
    pip_adhoc_build_system_requires = os.environ.get("_PEX_PIP_ADHOC_BUILD_SYSTEM_REQUIRES")
    if pip_adhoc_build_system_requires:
        build_system_requires.extend(json.loads(pip_adhoc_build_system_requires))

    extra_log_lines = []  # type: List[Text]

    pip_adhoc_requirement = os.environ.get("_PEX_PIP_ADHOC_REQUIREMENT")
    if pip_adhoc_requirement:
        pip_requirement = parse_requirement_string(pip_adhoc_requirement)
        pip_from = "_PEX_PIP_ADHOC_REQUIREMENT={requirement}".format(requirement=pip_requirement)
    else:
        data = json.loads(
            subprocess.check_output(
                args=[
                    "gh",
                    "run",
                    "-R",
                    PIP_REPO,
                    "list",
                    "-b",
                    PIP_BRANCH,
                    "-w",
                    PIP_WORKFLOW,
                    "-e",
                    "push",
                    "-s",
                    "success",
                    "-L1",
                    "--json",
                    "createdAt,displayTitle,headSha",
                ]
            )
        )
        if not data:
            raise RunError(
                "There were no green commits found for the {repo} {branch} branch in the "
                "{workflow} workflow.".format(
                    repo=PIP_REPO, branch=PIP_BRANCH, workflow=PIP_WORKFLOW
                )
            )
        green_ci_run = data[0]
        commit = green_ci_run["headSha"]
        pip_requirement = parse_requirement_string(
            "pip @ git+https://github.com/{repo}@{sha}".format(repo=PIP_REPO, sha=commit)
        )

        pip_from = "green {workflow} commit: https://github.com/{repo}/commit/{commit}".format(
            workflow=PIP_WORKFLOW, repo=PIP_REPO, commit=commit
        )
        extra_log_lines.append(
            to_unicode("> {created_at}: {pr_title}").format(
                created_at=dateutil.parser.isoparse(green_ci_run["createdAt"]).strftime("%c"),
                pr_title=green_ci_run["displayTitle"],
            )
        )

    with temporary_dir() as chroot:
        subprocess.check_call(
            args=["uv", "pip", "install", str(pip_requirement), "--target", chroot]
        )
        pip_metadata = DistMetadata.load(chroot)
        pip_version = pip_metadata.version
        pip_requires_python = pip_metadata.requires_python

    repo_and_commit = None  # type: Optional[Tuple[str, str]]
    if isinstance(pip_requirement, VCSRequirement) and pip_requirement.url.startswith(
        "https://github.com/"
    ):
        path_components = urlparse.urlparse(pip_requirement.url).path.lstrip("/").split("/")
        if len(path_components) >= 2:
            project = path_components[1].rsplit("@", 1)[0]
            repo = "{user}/{project}".format(user=path_components[0], project=project)
            commit = pip_requirement.commit or "HEAD"
            with URLFetcher().get_body_stream(
                "https://raw.githubusercontent.com/{repo}/{sha}/pyproject.toml".format(
                    repo=repo, sha=pip_requirement.commit or "HEAD"
                )
            ) as fp:
                pyproject = toml.load(fp)
            build_system_requires.extend(pyproject["build-system"]["requires"])
            repo_and_commit = repo, commit

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        build_requires = []  # type: List[str]
        if build_system_requires:
            build_requires.append(
                "| `[build-system] requires` | `{requirement}` |".format(
                    requirement=build_system_requires[0]
                )
            )
            build_requires.extend(
                "| | `{requirement}` |".format(requirement=requirement)
                for requirement in build_requires[1:]
            )
        build_requires_rows = "\n".join(build_requires)

        with open(summary_file, "ab") as summary_fp:
            if repo_and_commit:
                repo, commit = repo_and_commit
                output = subprocess.check_output(
                    args=[
                        "gh",
                        "api",
                        "repos/{repo}/commits/{sha}/pulls".format(repo=repo, sha=commit),
                        "--jq",
                        (
                            ".[] | {"
                            "url: .html_url, "
                            'message: .title + "\\n\\n" + .body, '
                            "created_at: .merged_at"
                            "}"
                        ),
                    ]
                ).decode("utf-8")
                if not output:
                    output = subprocess.check_output(
                        args=[
                            "gh",
                            "api",
                            "repos/{repo}/commits/{sha}".format(repo=repo, sha=commit),
                            "--jq",
                            (
                                "{"
                                "url: .html_url, "
                                "message: .commit.message, "
                                "created_at: .commit.committer.date"
                                "}"
                            ),
                        ]
                    ).decode("utf-8")

                data = json.loads(output)
                created_at = data["created_at"]
                message = data["message"].splitlines()
                url = data["url"]

                summary_fp.write(
                    dedent(
                        to_unicode(
                            """\
                            ## Pip {version}
                            | metadata          |                     |
                            | ----------------- | ------------------- |
                            | via               | {via}               |
                            | merged on         | {created_at}        |
                            | `Requires-Python` | `{requires_python}` |
                            {build_requires_rows}

                            ---

                            ### {title}

                            {body}
                            """
                        )
                    )
                    .format(
                        version=pip_version.raw,
                        via=url,
                        requires_python=pip_requires_python,
                        build_requires_rows=build_requires_rows,
                        created_at=dateutil.parser.isoparse(created_at).strftime("%c"),
                        title=message[0],
                        body="\n".join(message[1:]),
                    )
                    .encode("utf-8")
                )
            else:
                summary_fp.write(
                    dedent(
                        """\
                        ## Pip {version}
                        | metadata          |                     |
                        | ----------------- | ------------------- |
                        | via               | {via}               |
                        | `Requires-Python` | `{requires_python}` |
                        {build_requires_rows}
                        """
                    )
                    .format(
                        version=pip_version.raw,
                        via=pip_from,
                        requires_python=pip_requires_python,
                        build_requires_rows=build_requires_rows,
                    )
                    .encode("utf-8")
                )

    logger.warning("Using adhoc Pip (%s) from %s", pip_version.raw, pip_from)
    for log_line in extra_log_lines:
        logger.warning(log_line)
    return pip_version, pip_requires_python, build_system_requires, str(pip_requirement)


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

    if "adhoc" == os.environ.get("_PEX_PIP_VERSION"):
        version, requires_python, build_system_requires, requirement = resolve_pip_dev(logger)
        os.environ.update(
            _PEX_PIP_ADHOC_VERSION=version.raw,
            _PEX_PIP_ADHOC_REQUIREMENT=requirement,
            _PEX_PIP_ADHOC_BUILD_SYSTEM_REQUIRES=json.dumps(build_system_requires),
        )
        if requires_python:
            os.environ["_PEX_PIP_ADHOC_REQUIRES_PYTHON"] = str(requires_python)

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

    args = [sys.executable, "-m", "pytest", "-n", "auto", "-p", "testing.pytest_utils.shard"]

    os.environ["_PEX_REQUIRES_PYTHON"] = pex_dist.requires_python()

    # When run under dev-cmd, FORCE_COLOR=1 is set to propagate auto-detection of a color terminal.
    # This affects a handful of our tests; so we discard and let the --color option below control
    # our own color output.
    # TODO(John Sirois): Work with dev-cmd on this, it seems inappropriate to be using FORCE_COLOR
    #  like this.
    os.environ.pop("FORCE_COLOR", None)
    if options.color:
        args.extend(["--color", "yes"])

    if options.it:
        args.append("tests/integration")
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
    try:
        sys.exit(main())
    except (CalledProcessError, RunError) as e:
        sys.exit(str(e))
