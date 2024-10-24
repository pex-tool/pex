# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
from abc import abstractmethod

from pex.jobs import Job
from pex.typing import TYPE_CHECKING, Generic

if TYPE_CHECKING:
    from typing import Callable, Iterable, Optional, TypeVar, Union

    _T = TypeVar("_T")


class LogAnalyzer(object):
    class Complete(Generic["_T"]):
        def __init__(self, data=None):
            # type: (Optional[_T]) -> None
            self.data = data

    class Continue(Generic["_T"]):
        def __init__(self, data=None):
            # type: (Optional[_T]) -> None
            self.data = data

    @abstractmethod
    def should_collect(self, returncode):
        # type: (int) -> bool
        """Return `True` if the pip log should be analyzed given the pip job `returncode`."""

    @abstractmethod
    def analyze(self, line):
        # type: (str) -> Union[Complete, Continue]
        """Analyze the given log line.

        Returns a value indicating whether or not analysis is complete.
        """

    def analysis_completed(self):
        # type: () -> None
        """Called to indicate the log analysis is complete."""


class ErrorMessage(str):
    pass


if TYPE_CHECKING:
    ErrorAnalysis = Union[LogAnalyzer.Complete[ErrorMessage], LogAnalyzer.Continue[ErrorMessage]]


class ErrorAnalyzer(LogAnalyzer):
    def should_collect(self, returncode):
        # type: (int) -> bool
        return returncode != 0

    @abstractmethod
    def analyze(self, line):
        # type: (str) -> ErrorAnalysis
        """Analyze the given log line.

        Returns a value indicating whether or not analysis is complete.
        """


class LogScrapeJob(Job):
    def __init__(
        self,
        command,  # type: Iterable[str]
        process,  # type: subprocess.Popen
        log,  # type: str
        log_analyzers,  # type: Iterable[LogAnalyzer]
        finalizer=None,  # type: Optional[Callable[[int], None]]
    ):
        # type: (...) -> None
        self._log = log
        self._log_analyzers = list(log_analyzers)
        super(LogScrapeJob, self).__init__(command, process, finalizer=finalizer, context="pip")

    def _check_returncode(self, stderr=None):
        # type: (Optional[bytes]) -> None
        activated_analyzers = [
            analyzer
            for analyzer in self._log_analyzers
            if analyzer.should_collect(self._process.returncode)
        ]
        analyzed_stderr = b""  # type: bytes
        if activated_analyzers:
            collected = []
            # A process may fail so early that there is no log file to analyze.
            # We assume that if this is the case, the superclass _check_returncode will
            # express the underlying cause of that failure in a way useful to the user.
            if os.path.isfile(self._log):
                with open(self._log, "r") as fp:
                    for line in fp:
                        if not activated_analyzers:
                            break
                        for index, analyzer in tuple(enumerate(activated_analyzers)):
                            result = analyzer.analyze(line)
                            if isinstance(result.data, ErrorMessage):
                                collected.append(result.data)
                            if isinstance(result, LogAnalyzer.Complete):
                                activated_analyzers.pop(index).analysis_completed()
                                if not activated_analyzers:
                                    break
                for analyzer in activated_analyzers:
                    analyzer.analysis_completed()
            if collected:
                analyzed_stderr = "".join(collected).encode("utf-8")

        # Fall back to displaying the Pip logs in full if we have no stderr output or analysis. It's
        # likely overwhelming, but better than silence and useful for debugging.
        if (
            not stderr
            and not analyzed_stderr
            and self._process.returncode != 0
            and os.path.isfile(self._log)
        ):
            with open(self._log, "rb") as fp:
                analyzed_stderr = fp.read()

        super(LogScrapeJob, self)._check_returncode(stderr=(stderr or b"") + analyzed_stderr)
