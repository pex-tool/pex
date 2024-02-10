# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import errno
import os
import re
from threading import Condition, Event, Thread
from types import TracebackType

from pex.compatibility import get_stdout_bytes_buffer
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, BinaryIO, Iterable, Optional, Pattern, Type


class Tailer(Thread):
    @classmethod
    def tail(
        cls,
        path,  # type: str
        encoding="utf-8",  # type: str
        filters=(),  # type: Iterable[Pattern]
        poll_interval=0.1,  # type: float
        output=get_stdout_bytes_buffer(),  # type: BinaryIO
    ):
        # type: (...) -> Tailer
        tailer = cls(
            path, encoding=encoding, filters=filters, poll_interval=poll_interval, output=output
        )
        tailer.start()
        return tailer

    def __init__(
        self,
        path,  # type: str
        encoding="utf-8",  # type: str
        filters=(),  # type: Iterable[Pattern]
        poll_interval=0.1,  # type: float
        output=get_stdout_bytes_buffer(),  # type: BinaryIO
    ):
        # type: (...) -> None
        super(Tailer, self).__init__(name="Tailing {path}".format(path=path))
        self.daemon = True

        self._path = path
        self._encoding = encoding
        self._filters = filters or [re.compile(r".*")]
        self._poll_interval = poll_interval
        self._output = output

        self._offset = 0
        self._observer = Condition()
        self._stopped = Event()

    def __enter__(self):
        # type: () -> Tailer
        if not self._stopped.is_set() and not self.is_alive():
            self.start()
        return self

    def __exit__(
        self,
        _exc_type,  # type: Optional[Type]
        _exc_val,  # type: Optional[Any]
        _exc_tb,  # type: Optional[TracebackType]
    ):
        # type: (...) -> None
        self.stop()

    def run(self):
        # type: () -> None
        while not self._stopped.is_set():
            if not self._tail():
                self._stopped.wait(self._poll_interval)
        self._tail()

    def _tail(self):
        # type: () -> bool
        try:
            offset = os.path.getsize(self._path)
            if offset <= self._offset:
                # We do not handle generic tailing here where the file may be truncated and then
                # re-grow. The Pip log case is a simple always growing file.
                return False
        except OSError as e:
            if e.errno == errno.ENOENT:
                # The file may not exist yet; so we just wait for it to appear.
                return False
            raise e

        with open(self._path, "rb") as fp:
            fp.seek(self._offset)
            while fp.tell() < offset:
                line_bytes = fp.readline()
                line = line_bytes.decode(self._encoding)
                for pattern in self._filters:
                    match = pattern.match(line)
                    if match:
                        if match.groups():
                            eol = re.search(r"(?P<eol>\r\n|\r|\n)$", line)
                            self._output.write(
                                "{groups}{eol}".format(
                                    groups="".join(match.groups()),
                                    eol=eol.group("eol") if eol else "",
                                ).encode(self._encoding)
                            )
                        else:
                            self._output.write(line_bytes)
                        break
            self._offset = fp.tell()

        self._notify_observers()
        return True

    def _notify_observers(self):
        # type: () -> None
        with self._observer:
            self._observer.notify_all()

    def observe(self, timeout=None):
        # type: (Optional[float]) -> None
        """Wait for at least one new line of tailer output to be observable.

        Waits forever unless `timeout` is specified, in which case wait at most that many seconds,
        but returns immediately if the tailer is stopped.
        """
        if not self._stopped.is_set():
            with self._observer:
                self._observer.wait(timeout=timeout)

    def stop(self):
        # type: () -> None
        self._stopped.set()
        self.join()
