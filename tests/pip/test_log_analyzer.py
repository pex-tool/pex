# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess
from textwrap import dedent

import pytest

from pex.executables import chmod_plus_x
from pex.jobs import Job
from pex.pip.log_analyzer import ErrorAnalyzer, ErrorMessage, LogAnalyzer, LogScrapeJob
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class NoopErrorAnalyzer(ErrorAnalyzer):
    def analyze(self, line):
        return self.Complete()


@attr.s
class FirstLineErrorAnalyzer(ErrorAnalyzer):
    _error_message = attr.ib(default=None, init=False)  # type: Optional[ErrorMessage]

    def analyze(self, line):
        if self._error_message:
            return self.Complete()
        self._error_message = ErrorMessage(line)
        return self.Continue(self._error_message)


@pytest.fixture
def log(tmpdir):
    # type: (Any) -> str

    log = os.path.join(str(tmpdir), "pip.log")
    with open(log, "w") as fp:
        fp.write(
            dedent(
                """\
                Multi-line log output.
                Line 2.
                Key insight!
                Line 4.
                Last line.
                """
            )
        )
    return log


@pytest.fixture
def script(tmpdir):
    # type: (Any) -> str

    script = os.path.join(str(tmpdir), "exe.sh")
    with open(script, "w") as fp:
        fp.write(
            dedent(
                """\
                #!/bin/sh

                exit 42
                """
            )
        )
    chmod_plus_x(script)
    return script


def assert_job_failure(
    log,  # type: str
    script,  # type: str
    *log_analyzers  # type: LogAnalyzer
):
    # type: (...) -> str

    process = subprocess.Popen(args=[script])
    process.wait()

    finalized = []
    with pytest.raises(Job.Error) as exc_info:
        LogScrapeJob(
            command=[script],
            process=process,
            log=log,
            log_analyzers=log_analyzers,
            finalizer=lambda code: finalized.append(code),
        ).wait()
    assert [42] == finalized
    return str(exc_info.value)


def test_errored_log_scrape_job_with_analysis(
    tmpdir,  # type: Any
    log,  # type: str
    script,  # type: str
):
    # type: (...) -> None

    error_msg = assert_job_failure(log, script, NoopErrorAnalyzer(), FirstLineErrorAnalyzer())
    assert (
        "pip: Executing {script} failed with 42\n"
        "STDERR:\n"
        "Multi-line log output.\n".format(script=script)
    ) == error_msg


def test_errored_log_scrape_job_with_no_analysis(
    tmpdir,  # type: Any
    log,  # type: str
    script,  # type: str
):
    # type: (...) -> None

    error_msg = assert_job_failure(log, script, NoopErrorAnalyzer())
    assert (
        "pip: Executing {script} failed with 42\n"
        "STDERR:\n"
        "Multi-line log output.\n"
        "Line 2.\n"
        "Key insight!\n"
        "Line 4.\n"
        "Last line.\n".format(script=script)
    ) == error_msg


def test_errored_log_scrape_job_with_no_analyzers(
    tmpdir,  # type: Any
    log,  # type: str
    script,  # type: str
):
    # type: (...) -> None

    error_msg = assert_job_failure(log, script)
    assert (
        "pip: Executing {script} failed with 42\n"
        "STDERR:\n"
        "Multi-line log output.\n"
        "Line 2.\n"
        "Key insight!\n"
        "Line 4.\n"
        "Last line.\n".format(script=script)
    ) == error_msg
