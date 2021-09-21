# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import functools
from argparse import ArgumentParser, _ActionsContainer, _SubParsersAction
from contextlib import contextmanager

from pex.commands.command import Command, Result
from pex.typing import TYPE_CHECKING, Generic, cast

if TYPE_CHECKING:
    from typing import Callable, Iterator, Optional, Type, TypeVar

    _C = TypeVar("_C", bound="BuildTimeCommand")


class BuildTimeCommand(Command):
    class Subcommands(Generic["_C"]):
        def __init__(
            self,
            subparsers,  # type: _SubParsersAction
        ):
            # type: (...) -> None
            self._subparsers = subparsers

        @contextmanager
        def parser(
            self,
            name,  # type: str
            help,  # type: str
            func=None,  # type: Optional[Callable[[_C], Result]]
        ):
            # type: (...) -> Iterator[ArgumentParser]
            subcommand_parser = self._subparsers.add_parser(name=name, help=help)
            yield subcommand_parser
            if func:
                subcommand_parser.set_defaults(subcommand_func=func)
                Command.register_global_arguments(subcommand_parser)

    @classmethod
    def add_arguments(cls, parser):
        # type: (ArgumentParser) -> None
        cls.add_extra_arguments(parser)
        if not parser.get_default("subcommand_func"):
            cls.register_global_arguments(parser)

    @classmethod
    def add_extra_arguments(cls, parser):
        # type: (ArgumentParser) -> None
        pass

    @classmethod
    def create_subcommands(
        cls,  # type: Type[_C]
        parser,  # type: ArgumentParser
        description=None,  # type: Optional[str]
    ):
        # type: (...) -> Subcommands[_C]
        parser.set_defaults(subcommand_func=functools.partial(cls.show_help, parser))
        subparsers = parser.add_subparsers(description=description)
        return cls.Subcommands(subparsers)

    def run(self):
        # type: (_C) -> Result
        subcommand_func = cast(
            "Optional[Callable[[_C], Result]]", getattr(self.options, "subcommand_func", None)
        )
        if subcommand_func is not None:
            return subcommand_func(self)
        raise NotImplementedError()
