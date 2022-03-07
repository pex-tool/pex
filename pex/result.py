# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import sys

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Callable, TypeVar, Union

    import attr  # vendor:skip

    _T = TypeVar("_T")
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Result(object):
    exit_code = attr.ib()  # type: int
    _message = attr.ib(default="")  # type: str

    @property
    def is_error(self):
        # type: () -> bool
        return self.exit_code != 0

    def maybe_display(self):
        # type: () -> None
        if not self._message:
            return
        print(self._message, file=sys.stderr if self.is_error else sys.stdout)

    def __str__(self):
        # type: () -> str
        return self._message


class Ok(Result):
    def __init__(self, message=""):
        # type: (str) -> None
        super(Ok, self).__init__(exit_code=0, message=message)


class Error(Result):
    def __init__(
        self,
        message="",  # type: str
        exit_code=1,  # type: int
    ):
        # type: (...) -> None
        if exit_code == 0:
            raise ValueError("An Error must have a non-zero exit code; given: {}".format(exit_code))
        super(Error, self).__init__(exit_code=exit_code, message=message)


@attr.s(frozen=True)
class ResultError(Exception):
    """Wraps an Error in an exception for use in short-circuiting via `try_` / `catch`."""

    error = attr.ib()  # type: Error

    def __str__(self):
        # type: () -> str
        return str(self.error)


def try_(result):
    # type: (Union[_T, Error]) -> _T
    """Return the result unless it's an `Error`.

    Paired with `catch` at a higher layer, this allows for ~checked exceptions without the line
    noise of try / except handling.

    :param result: a result containing a successful value or else an error.
    :return: the result if not an error.
    :raise: :class:`ResultError` if the result is an error.
    """
    if isinstance(result, Error):
        raise ResultError(error=result)
    return result


def catch(
    func,  # type: Callable[..., _T]
    *args,  # type: Any
    **kwargs  # type: Any
):
    # type: (...) -> Union[_T, Error]
    """Execute the given function in a context that handles short-circuit error returns.

    :param func: The function to execute.
    :param args: Any arguments to be passed to func.
    :param kwargs: Any keyword arguments to be passed to func.
    :return: The result of the function or an error if any error was returned in the call stack of
             the function.
    """
    try:
        return func(*args, **kwargs)
    except ResultError as e:
        return e.error
