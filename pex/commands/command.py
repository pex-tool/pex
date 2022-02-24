# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import functools
import json
import logging
import os
import subprocess
import sys
import tempfile
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace, _ActionsContainer
from contextlib import contextmanager

from pex import pex_warnings
from pex.argparse import HandleBoolAction
from pex.common import safe_mkdtemp, safe_open
from pex.result import Error, Ok, Result
from pex.typing import TYPE_CHECKING, Generic, cast
from pex.variables import ENV, Variables
from pex.version import __version__

if TYPE_CHECKING:
    from typing import (
        IO,
        Any,
        Dict,
        Iterable,
        Iterator,
        NoReturn,
        Optional,
        Sequence,
        Type,
        TypeVar,
    )

    import attr  # vendor:skip
else:
    from pex.third_party import attr

if TYPE_CHECKING:
    _T = TypeVar("_T")


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

    @staticmethod
    def register_global_arguments(
        parser,  # type: _ActionsContainer
        include_verbosity=True,  # type: bool
    ):
        # type: (...) -> None
        register_global_arguments(parser, include_verbosity=include_verbosity)

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
        parser,  # type: _ActionsContainer
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
        parser,  # type: _ActionsContainer
        entity,  # type: str
        include_switch=True,  # type: bool
    ):
        flags = ("-i", "--indent") if include_switch else ("--indent",)
        parser.add_argument(
            *flags,
            type=int,
            default=None,
            help="Pretty-print {entity} json with the given indent.".format(entity=entity)
        )

    @staticmethod
    def dump_json(
        options,  # type: Namespace
        data,  # type: Dict[str, Any]
        out,  # type: IO
        **json_dump_kwargs  # type: Any
    ):
        json.dump(data, out, indent=options.indent, **json_dump_kwargs)


def register_global_arguments(
    parser,  # type: _ActionsContainer
    include_verbosity=True,  # type: bool
):
    # type: (...) -> None
    """Register Pex global environment configuration options with the given parser.

    :param parser: The parser to register global options with.
    :param include_verbosity: Whether to include the verbosity option `-v`.
    """

    group = parser.add_argument_group(title="Global options")
    if include_verbosity:
        group.add_argument(
            "-v",
            dest="verbosity",
            action="count",
            default=0,
            help="Turn on logging verbosity, may be specified multiple times.",
        )
    group.add_argument(
        "--emit-warnings",
        "--no-emit-warnings",
        dest="emit_warnings",
        action=HandleBoolAction,
        default=True,
        help=(
            "Emit runtime UserWarnings on stderr. If false, only emit them when PEX_VERBOSE "
            "is set."
        ),
    )
    group.add_argument(
        "--pex-root",
        dest="pex_root",
        default=None,
        help=(
            "Specify the pex root used in this invocation of pex "
            "(if unspecified, uses {}).".format(ENV.PEX_ROOT)
        ),
    )
    group.add_argument(
        "--disable-cache",
        dest="disable_cache",
        default=False,
        action="store_true",
        help="Disable caching in the pex tool entirely.",
    )

    group.add_argument(
        "--cache-dir",
        dest="cache_dir",
        default=None,
        help=(
            "DEPRECATED: Use --pex-root instead. The local cache directory to use for speeding up "
            "requirement lookups."
        ),
    )
    group.add_argument(
        "--tmpdir",
        dest="tmpdir",
        default=tempfile.gettempdir(),
        help="Specify the temporary directory Pex and its subprocesses should use.",
    )
    group.add_argument(
        "--rcfile",
        dest="rc_file",
        default=None,
        help=(
            "An additional path to a pexrc file to read during configuration parsing, in addition "
            "to reading `/etc/pexrc` and `~/.pexrc`. If `PEX_IGNORE_RCFILES=true`, then all rc "
            "files will be ignored."
        ),
    )


class GlobalConfigurationError(Exception):
    """Indicates an error processing global options."""


@contextmanager
def _configured_env(options):
    # type: (Namespace) -> Iterator[None]
    if options.rc_file or not ENV.PEX_IGNORE_RCFILES:
        with ENV.patch(**Variables(rc=options.rc_file).copy()):
            yield
    else:
        yield


@contextmanager
def global_environment(options):
    # type: (Namespace) -> Iterator[Dict[str, str]]
    """Configures the Pex global environment.

    This includes configuration of basic Pex infrastructure like logging, warnings and the
    `PEX_ROOT` to use.

    :param options: The global options registered by `register_global_arguments`.
    :yields: The configured global environment.
    :raises: :class:`GlobalConfigurationError` if invalid global option values were specified.
    """
    with _configured_env(options):
        verbosity = Variables.PEX_VERBOSE.strip_default(ENV)
        if verbosity is None:
            verbosity = getattr(options, "verbosity", 0)

        emit_warnings = True
        if not options.emit_warnings:
            emit_warnings = False
        if emit_warnings and ENV.PEX_EMIT_WARNINGS is not None:
            emit_warnings = ENV.PEX_EMIT_WARNINGS

        with ENV.patch(PEX_VERBOSE=str(verbosity), PEX_EMIT_WARNINGS=str(emit_warnings)):
            pex_warnings.configure_warnings(env=ENV)

            # Ensure the TMPDIR is an absolute path (So subprocesses that change CWD can find it)
            # and that it exists.
            tmpdir = os.path.realpath(options.tmpdir)
            if not os.path.exists(tmpdir):
                raise GlobalConfigurationError(
                    "The specified --tmpdir does not exist: {}".format(tmpdir)
                )
            if not os.path.isdir(tmpdir):
                raise GlobalConfigurationError(
                    "The specified --tmpdir is not a directory: {}".format(tmpdir)
                )
            tempfile.tempdir = os.environ["TMPDIR"] = tmpdir

            if options.cache_dir:
                pex_warnings.warn("The --cache-dir option is deprecated, use --pex-root instead.")
                if options.pex_root and options.cache_dir != options.pex_root:
                    raise GlobalConfigurationError(
                        "Both --cache-dir and --pex-root were passed with conflicting values. "
                        "Just set --pex-root."
                    )

            if options.disable_cache:

                def warn_ignore_pex_root(set_via):
                    pex_warnings.warn(
                        "The pex root has been set via {via} but --disable-cache is also set. "
                        "Ignoring {via} and disabling caches.".format(via=set_via)
                    )

                if options.cache_dir:
                    warn_ignore_pex_root("--cache-dir")
                elif options.pex_root:
                    warn_ignore_pex_root("--pex-root")
                elif os.environ.get("PEX_ROOT"):
                    warn_ignore_pex_root("PEX_ROOT")

                pex_root = safe_mkdtemp()
            else:
                pex_root = options.cache_dir or options.pex_root or ENV.PEX_ROOT

            with ENV.patch(PEX_ROOT=pex_root, TMPDIR=tmpdir) as env:
                yield env


if TYPE_CHECKING:
    _C = TypeVar("_C", bound=Command)


class Main(Generic["_C"]):
    def __init__(
        self,
        command_types,  # type: Iterable[Type[_C]]
        description=None,  # type: Optional[str]
        subparsers_description=None,  # type: Optional[str]
        prog=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        self._prog = prog
        self._description = description or self.__doc__
        self._subparsers_description = subparsers_description
        self._command_types = command_types

    def add_arguments(self, parser):
        # type: (ArgumentParser) -> None
        pass

    @contextmanager
    def parsed_command(self, args=None):
        # type: (Optional[Sequence[str]]) -> Iterator[_C]
        logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)

        # By default, let argparse derive prog from sys.argv[0].
        prog = self._prog
        if os.path.basename(sys.argv[0]) == "__main__.py":
            prog = "{python} -m {module}".format(
                python=sys.executable, module=".".join(type(self).__module__.split(".")[:-1])
            )

        parser = ArgumentParser(
            prog=prog,
            formatter_class=ArgumentDefaultsHelpFormatter,
            description=self._description,
        )
        parser.add_argument("-V", "--version", action="version", version=__version__)
        parser.set_defaults(command_type=functools.partial(Command.show_help, parser))
        register_global_arguments(parser)
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

        options = parser.parse_args(args=args)
        with global_environment(options):
            command_type = cast("Type[_C]", options.command_type)
            yield command_type(options)
