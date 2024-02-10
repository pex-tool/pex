# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import re
from contextlib import contextmanager
from types import TracebackType

from pex.pip.tailer import Tailer
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, BinaryIO, Iterator, Optional, Pattern, Type

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class TailerTestHarness(object):
    @classmethod
    @contextmanager
    def create(
        cls,
        tmpdir,  # type: Any
        *filters  # type: Pattern
    ):
        # type: (...) -> Iterator[TailerTestHarness]

        log = os.path.join(str(tmpdir), "log")
        tail_to = os.path.join(str(tmpdir), "redirect")

        with open(tail_to, "wb") as tail_to_fp, Tailer(
            path=log, filters=filters, poll_interval=0.01, output=tail_to_fp
        ) as tailer:
            yield TailerTestHarness(log=log, tail_to_fp=tail_to_fp, tailer=tailer)

    _log = attr.ib()  # type: str
    _tail_to_fp = attr.ib()  # type: BinaryIO
    _tailer = attr.ib()  # type: Tailer

    def __enter__(self):
        # type: () -> TailerTestHarness
        self._tailer.__enter__()
        return self

    def __exit__(
        self,
        exc_type,  # type: Optional[Type]
        exc_val,  # type: Optional[Any]
        exc_tb,  # type: Optional[TracebackType]
    ):
        # type: (...) -> None
        self._tailer.__exit__(exc_type, exc_val, exc_tb)

    def write_log(self, content):
        # type: (str) -> None
        with open(self._log, "a") as log_fp:
            log_fp.write(content)

    def assert_redirected_content(
        self,
        content,  # type: str
        timeout=None,  # type: Optional[float]
    ):
        # type: (...) -> None

        self._tailer.observe(timeout=timeout)
        self._tail_to_fp.flush()
        with open(self._tail_to_fp.name) as observe_fp:
            assert content == observe_fp.read()


def test_tailer_all_lines(tmpdir):
    # type: (Any) -> None

    with TailerTestHarness.create(tmpdir) as harness:
        harness.assert_redirected_content("", timeout=0.1)

        harness.write_log("1st line\n")
        harness.assert_redirected_content("1st line\n")

        harness.write_log("2nd line\n")
        harness.assert_redirected_content("1st line\n2nd line\n")

        harness.write_log("3rd line\n4th line\n")
        harness.assert_redirected_content("1st line\n2nd line\n3rd line\n4th line\n")

        harness.write_log("tail content")
        harness.assert_redirected_content("1st line\n2nd line\n3rd line\n4th line\ntail content")


def test_tailer_filter(tmpdir):
    # type: (Any) -> None

    with TailerTestHarness.create(
        tmpdir,
        re.compile(r"^2nd.*"),
        re.compile(r"^(\S+) content$"),
        re.compile(r"^multi (\S+) (\S+).*$"),
    ) as harness:
        harness.assert_redirected_content("", timeout=0.1)

        harness.write_log("1st line\n")
        harness.assert_redirected_content("")

        harness.write_log("2nd line\n")
        harness.assert_redirected_content("2nd line\n")

        harness.write_log("3rd line\n4th line\n")
        harness.assert_redirected_content("2nd line\n")

        harness.write_log("multi one two three\n")
        harness.assert_redirected_content("2nd line\nonetwo\n")

        harness.write_log("tail content")
        harness.assert_redirected_content("2nd line\nonetwo\ntail")
