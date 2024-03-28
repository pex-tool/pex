# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import functools
from argparse import ArgumentParser, _SubParsersAction
from contextlib import contextmanager

from pex.commands.command import Command
from pex.result import Error, Result
from pex.typing import TYPE_CHECKING, Generic, cast

if TYPE_CHECKING:
    from typing import Callable, ClassVar, Iterator, Optional, Type, TypeVar

    _C = TypeVar("_C", bound="BuildTimeCommand")


class BuildTimeCommand(Command):
    class Subcommands(Generic["_C"]):
        def __init__(
            self,
            subparsers,  # type: _SubParsersAction
            include_verbosity,  # type: bool
        ):
            # type: (...) -> None
            self._subparsers = subparsers
            self._include_verbosity = include_verbosity

        @contextmanager
        def parser(
            self,
            name,  # type: str
            help,  # type: str
            func=None,  # type: Optional[Callable[[_C], Result]]
            include_verbosity=None,  # type: Optional[bool]
            passthrough_args=None,  # type: Optional[str]
        ):
            # type: (...) -> Iterator[ArgumentParser]
            subcommand_parser = self._subparsers.add_parser(name=name, help=help)
            yield subcommand_parser
            if func:
                if passthrough_args:
                    # N.B.: This is a dummy arg for usage string display purposes; thus the "_" name.
                    subcommand_parser.add_argument(
                        "_", metavar="-- passthrough args", nargs="*", help=passthrough_args
                    )
                else:
                    func = functools.partial(
                        BuildTimeCommand._check_no_passthrough_args_and_run,
                        subcommand_name=name,
                        subcommand_func=func,
                    )
                subcommand_parser.set_defaults(subcommand_func=func)
                Command.register_global_arguments(
                    subcommand_parser,
                    include_verbosity=include_verbosity
                    if include_verbosity is not None
                    else self._include_verbosity,
                )

    include_global_verbosity_option = True  # type: ClassVar[bool]

    @classmethod
    def add_arguments(cls, parser):
        # type: (ArgumentParser) -> None
        cls.add_extra_arguments(parser)
        if not parser.get_default("subcommand_func"):
            cls.register_global_arguments(
                parser, include_verbosity=cls.include_global_verbosity_option
            )

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
        return cls.Subcommands(subparsers, include_verbosity=cls.include_global_verbosity_option)

    def _check_no_passthrough_args_and_run(
        self,
        subcommand_name,  # type: str
        subcommand_func,  # type: Callable[[BuildTimeCommand], Result]
    ):
        # type: (...) -> Result
        if self.passthrough_args is not None:
            return Error(
                "The {subcommand} {command} subcommand does not accept pass through args.".format(
                    subcommand=subcommand_name, command=self.name()
                )
            )
        return subcommand_func(self)

    def run(self):
        # type: (_C) -> Result
        subcommand_func = cast(
            "Optional[Callable[[_C], Result]]", getattr(self.options, "subcommand_func", None)
        )
        if subcommand_func is not None:
            return subcommand_func(self)
        raise NotImplementedError()
