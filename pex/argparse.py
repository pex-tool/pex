# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import shlex
from argparse import Action, ArgumentError, ArgumentParser, Namespace

from pex.os import WINDOWS
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Callable, Optional, Sequence, Text, Type, Union


class HandleBoolAction(Action):
    """An action for bool options that parses `--no-foo` or `--not-foo` as `--foo=False`"""

    def __init__(self, *args, **kwargs):
        kwargs["nargs"] = 0
        super(HandleBoolAction, self).__init__(*args, **kwargs)

    def __call__(
        self,
        parser,  # type: ArgumentParser
        namespace,  # type: Namespace
        values,  # type: Union[str, Sequence[Any], None]
        option_string=None,  # type: Optional[Text]
    ):
        # type: (...) -> None
        if not isinstance(option_string, str):
            raise ArgumentError(
                self, "Unexpected {dest} value: {values}".format(dest=self.dest, values=values)
            )
        setattr(namespace, self.dest, not option_string.startswith("--no"))


class InjectEnvAction(Action):
    def __call__(
        self,
        parser,  # type: ArgumentParser
        namespace,  # type: Namespace
        values,  # type: Union[str, Sequence[Any], None]
        option_string=None,  # type: Optional[Text]
    ):
        # type: (...) -> None
        if not isinstance(values, str):
            raise ArgumentError(
                self, "Unexpected {dest} value: {values}".format(dest=self.dest, values=values)
            )
        components = values.split("=", 1)
        if len(components) != 2:
            raise ArgumentError(
                self,
                "Environment variable values must be of the form `name=value`. "
                "Given: {value}".format(value=values),
            )
        self.default.append(tuple(components))


class InjectArgAction(Action):
    def __call__(
        self,
        parser,  # type: ArgumentParser
        namespace,  # type: Namespace
        values,  # type: Union[str, Sequence[Any], None]
        option_string=None,  # type: Optional[Text]
    ):
        # type: (...) -> None
        if not isinstance(values, str):
            raise ArgumentError(
                self, "Unexpected {dest} value: {values}".format(dest=self.dest, values=values)
            )
        self.default.extend(shlex.split(values, posix=not WINDOWS))


def parse_action(
    parse_func,  # type: Callable
    optional_value=False,  # type: bool
):
    # type: (...) -> Type[Action]

    class ParseAction(Action):
        def __call__(
            self,
            parser,  # type: ArgumentParser
            namespace,  # type: Namespace
            values,  # type: Union[str, Sequence[Any], None]
            option_string=None,  # type: Optional[Text]
        ):
            # type: (...) -> None
            if isinstance(values, str) or (optional_value and values is None):
                setattr(namespace, self.dest, parse_func(values))
            else:
                raise ArgumentError(
                    self, "Unexpected {dest} value: {values}".format(dest=self.dest, values=values)
                )

    return ParseAction
