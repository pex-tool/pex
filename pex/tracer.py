# Copyright 2014 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import sys
import threading
import time
from contextlib import contextmanager

from pex.typing import TYPE_CHECKING, cast
from pex.variables import ENV

__all__ = ("TRACER", "TraceLogger")

if TYPE_CHECKING:
    from typing import IO, Any, Callable, Iterator, List, Optional


class Trace(object):
    __slots__ = ("msg", "verbosity", "parent", "children", "_clock", "_start", "_stop")

    def __init__(self, msg, parent=None, verbosity=1, clock=time):
        # type: (str, Optional[Trace], int, Any) -> None
        self.msg = msg
        self.verbosity = verbosity
        self.parent = parent
        if parent is not None:
            parent.children.append(self)
        self.children = []  # type: List[Trace]
        self._clock = clock
        self._start = cast(float, self._clock.time())
        self._stop = cast("Optional[float]", None)

    def stop(self):
        # type: () -> None
        self._stop = self._clock.time()

    def duration(self):
        # type: () -> float
        assert self._stop is not None
        return self._stop - self._start


class TraceLogger(object):
    """A multi-threaded tracer."""

    def __init__(self, predicate=None, output=sys.stderr, clock=time, prefix=""):
        # type: (Optional[Callable[[int], bool]], IO, Any, str) -> None
        """If predicate specified, it should take a "verbosity" integer and determine whether or not
        to log, e.g.

          def predicate(verbosity):
            try:
              return verbosity < int(os.environ.get('APP_VERBOSITY', 0))
            except ValueError:
              return False

        output defaults to sys.stderr, but can take any file-like object.
        """
        self._predicate = predicate or (lambda verbosity: True)
        self._length = cast("Optional[int]", None)
        self._output = output
        self._isatty = getattr(output, "isatty", False) and output.isatty()
        self._lock = threading.RLock()
        self._local = threading.local()
        self._clock = clock
        self._prefix = prefix

    def should_log(self, V):
        # type: (int) -> bool
        return self._predicate(V)

    def log(self, msg, V=1, end="\n"):
        # type: (str, int, str) -> None
        if not self.should_log(V):
            return
        if not self._isatty and end == "\r":
            # force newlines if we're not a tty
            end = "\n"
        trailing_whitespace = ""
        with self._lock:
            if self._length and self._length > (len(self._prefix) + len(msg)):
                trailing_whitespace = " " * (self._length - len(msg) - len(self._prefix))
            self._output.write("".join([self._prefix, msg, trailing_whitespace, end]))
            self._output.flush()
            self._length = (len(self._prefix) + len(msg)) if end == "\r" else 0

    def _print_trace_snippet(self, node):
        # type: (Trace) -> None
        node_verbosity = node.verbosity
        if not self.should_log(node_verbosity):
            return
        traces = []
        parent = node  # type: Optional[Trace]
        while parent:
            if self.should_log(parent.verbosity):
                traces.append(parent.msg)
            parent = parent.parent
        self.log(" :: ".join(reversed(traces)), V=node_verbosity, end="\r")

    def _print_trace(self, node, indent=0):
        # type: (Trace, int) -> None
        with self._lock:
            self.log(
                " " * indent + ("%s: %.1fms" % (node.msg, 1000.0 * node.duration())),
                V=node.verbosity,
            )
            for child in node.children:
                self._print_trace(indent=indent + 2, node=child)

    @contextmanager
    def timed(self, msg, V=1):
        # type: (str, int) -> Iterator[None]
        parent = Trace(
            msg, parent=getattr(self._local, "parent", None), verbosity=V, clock=self._clock
        )
        self._local.parent = parent
        self._print_trace_snippet(parent)
        try:
            yield
        finally:
            parent.stop()
            if parent.parent is not None:
                self._local.parent = parent.parent
            else:
                self._print_trace(parent)
                self._local.parent = None


TRACER = TraceLogger(
    predicate=lambda verbosity: verbosity <= ENV.PEX_VERBOSE,
    prefix="pex: ",
)
