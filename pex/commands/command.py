# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import functools
import json
import logging
import os
import subprocess
import sys
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace
from contextlib import contextmanager

from pex.common import safe_open
from pex.typing import TYPE_CHECKING, Generic, cast
from pex.version import __version__

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import Any, Dict, Iterable, Iterator, IO, NoReturn, Optional, Type, TypeVar
else:
    from pex.third_party import attr


class Result(object):
    def __init__(
        self,
        exit_code,  # type: int
        message="",  # type: str
    ):
        # type: (...) -> None
        self._exit_code = exit_code
        self._message = message

    @property
    def exit_code(self):
        # type: () -> int
        return self._exit_code

    @property
    def is_error(self):
        # type: () -> bool
        return self._exit_code != 0

    def maybe_display(self):
        # type: () -> None
        if not self._message:
            return
        print(self._message, file=sys.stderr if self.is_error else sys.stdout)

    def __str__(self):
        # type: () -> str
        return self._message

    def __repr__(self):
        # type: () -> str
        return "{}(exit_code={!r}, message={!r})".format(
            type(self).__name__, self._exit_code, self._message
        )


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


def try_run_program(
    program,  # type: str
    args,  # type: Iterable[str]
    url=None,  # type: Optional[str]
    error=None,  # type: Optional[str]
    **kwargs  # type: Any
):
    # type: (...) -> Result
    try:
        subprocess.check_call([program] + list(args), **kwargs)
        return Ok()
    except OSError as e:
        msg = [error] if error else []
        msg.append("Do you have `{}` installed on the $PATH?: {}".format(program, e))
        if url:
            msg.append(
                "Find more information on `{program}` at {url}.".format(program=program, url=url)
            )
        return Error("\n".join(msg))
    except subprocess.CalledProcessError as e:
        return Error(str(e), exit_code=e.returncode)


def try_open_file(
    path,  # type: str
    error=None,  # type: Optional[str]
):
    # type: (...) -> Result
    opener, url = (
        ("xdg-open", "https://www.freedesktop.org/wiki/Software/xdg-utils/")
        if "Linux" == os.uname()[0]
        else ("open", None)
    )
    with open(os.devnull, "wb") as devnull:
        return try_run_program(opener, [path], url=url, error=error, stdout=devnull)


@attr.s(frozen=True)
class Command(object):
    @staticmethod
    def show_help(
        parser,  # type: ArgumentParser
        *_args,  # type: Any
        **_kwargs  # type: Any
    ):
        # type: (...) -> NoReturn
        parser.error("a subcommand is required")

    @classmethod
    def name(cls):
        # type: () -> str
        return cls.__name__.lower()

    @classmethod
    def description(cls):
        # type: () -> Optional[str]
        return cls.__doc__

    @classmethod
    def add_arguments(cls, parser):
        # type: (ArgumentParser) -> None
        pass

    options = attr.ib()  # type: Namespace


class OutputMixin(object):
    @staticmethod
    def add_output_option(
        parser,  # type: ArgumentParser
        entity,  # type: str
    ):
        # type: (...) -> None
        parser.add_argument(
            "-o",
            "--output",
            metavar="PATH",
            help=(
                "A file to output the {entity} to; STDOUT by default or when `-` is "
                "specified.".format(entity=entity)
            ),
        )

    @staticmethod
    def is_stdout(options):
        # type: (Namespace) -> bool
        return options.output == "-" or not options.output

    @classmethod
    @contextmanager
    def output(
        cls,
        options,  # type: Namespace
        binary=False,  # type: bool
    ):
        # type: (...) -> Iterator[IO]
        if cls.is_stdout(options):
            stdout = getattr(sys.stdout, "buffer", sys.stdout) if binary else sys.stdout
            yield stdout
        else:
            with safe_open(options.output, mode="wb" if binary else "w") as out:
                yield out


class JsonMixin(object):
    @staticmethod
    def add_json_options(
        parser,
        entity,
    ):
        parser.add_argument(
            "-i",
            "--indent",
            type=int,
            default=None,
            help="Pretty-print {entity} json with the given indent.".format(entity=entity),
        )

    @staticmethod
    def dump_json(
        options,  # type: Namespace
        data,  # type: Dict[str, Any]
        out,  # type: IO
        **json_dump_kwargs  # type: Any
    ):
        json.dump(data, out, indent=options.indent, **json_dump_kwargs)


if TYPE_CHECKING:
    _C = TypeVar("_C", bound=Command)


class Main(Generic["_C"]):
    def __init__(
        self,
        description,  # type: str
        command_types,  # type: Iterable[Type[_C]]
        subparsers_description=None,  # type: Optional[str]
        prog=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        self._prog = prog
        self._description = description
        self._subparsers_description = subparsers_description
        self._command_types = command_types

    def add_arguments(self, parser):
        # type: (ArgumentParser) -> None
        pass

    def parse_command(self):
        # type: () -> _C
        logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)

        # By default, let argparse derive prog from sys.argv[0].
        prog = self._prog
        if os.path.basename(sys.argv[0]) == "__main__.py":
            prog = "{python} {module}".format(
                python=sys.executable, module=".".join(__name__.split(".")[:-1])
            )

        parser = ArgumentParser(
            prog=prog,
            formatter_class=ArgumentDefaultsHelpFormatter,
            description=self._description,
        )
        parser.add_argument("-V", "--version", action="version", version=__version__)
        parser.set_defaults(command_type=functools.partial(Command.show_help, parser))
        self.add_arguments(parser)
        if self._command_types:
            subparsers = parser.add_subparsers(description=self._subparsers_description)
            for command_type in self._command_types:
                name = command_type.name()
                description = command_type.description()
                help_text = description.splitlines()[0] if description else None
                command_parser = subparsers.add_parser(
                    name,
                    formatter_class=ArgumentDefaultsHelpFormatter,
                    help=help_text,
                    description=description,
                )
                command_type.add_arguments(command_parser)
                command_parser.set_defaults(command_type=command_type)

        options = parser.parse_args()
        command_type = cast("Type[_C]", options.command_type)
        return command_type(options)
