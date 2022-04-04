# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""
The pex.bin.pex utility builds PEX environments and .pex files specified by
sources, requirements and their dependencies.
"""

from __future__ import absolute_import, print_function

import itertools
import json
import os
import sys
from argparse import Action, ArgumentDefaultsHelpFormatter, ArgumentParser
from textwrap import TextWrapper

from pex import pex_warnings
from pex.argparse import HandleBoolAction
from pex.commands.command import (
    GlobalConfigurationError,
    global_environment,
    register_global_arguments,
)
from pex.common import die, safe_mkdtemp
from pex.enum import Enum
from pex.inherit_path import InheritPath
from pex.layout import Layout, maybe_install
from pex.orderedset import OrderedSet
from pex.pex import PEX
from pex.pex_bootstrapper import ensure_venv
from pex.pex_builder import CopyMode, PEXBuilder
from pex.pex_info import PexInfo
from pex.resolve import requirement_options, resolver_options, target_configuration, target_options
from pex.resolve.lock_resolver import resolve_from_lock
from pex.resolve.pex_repository_resolver import resolve_from_pex
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import (
    LockRepositoryConfiguration,
    PexRepositoryConfiguration,
)
from pex.resolve.resolvers import Unsatisfiable
from pex.resolver import resolve
from pex.result import try_
from pex.targets import Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.variables import ENV, Variables
from pex.venv.bin_path import BinPath
from pex.version import __version__

if TYPE_CHECKING:
    from argparse import Namespace
    from typing import Dict, List, Optional

    from pex.resolve.resolver_options import ResolverConfiguration

CANNOT_SETUP_INTERPRETER = 102
INVALID_OPTIONS = 103


def log(msg, V=0):
    if V != 0:
        print(msg, file=sys.stderr)


class HandleVenvAction(Action):
    def __init__(self, *args, **kwargs):
        kwargs["nargs"] = "?"
        kwargs["choices"] = (BinPath.PREPEND.value, BinPath.APPEND.value)
        super(HandleVenvAction, self).__init__(*args, **kwargs)

    def __call__(self, parser, namespace, value, option_str=None):
        bin_path = BinPath.FALSE if value is None else BinPath.for_value(value)
        setattr(namespace, self.dest, bin_path)


class PrintVariableHelpAction(Action):
    def __call__(self, parser, namespace, values, option_str=None):
        for variable_name, variable_type, variable_help in Variables.iter_help():
            print("\n%s: %s\n" % (variable_name, variable_type))
            for line in TextWrapper(initial_indent=" " * 4, subsequent_indent=" " * 4).wrap(
                variable_help
            ):
                print(line)
        sys.exit(0)


def configure_clp_pex_resolution(parser):
    # type: (ArgumentParser) -> None
    group = parser.add_argument_group(
        title="Resolver options",
        description=(
            "Tailor how to find, resolve and translate the packages that get put into the PEX "
            "environment."
        ),
    )

    resolver_options.register(group, include_pex_repository=True, include_lock=True)

    group.add_argument(
        "--pex-path",
        dest="pex_path",
        type=str,
        default=None,
        help="A colon separated list of other pex files to merge into the runtime environment.",
    )


def configure_clp_pex_options(parser):
    # type: (ArgumentParser) -> None
    group = parser.add_argument_group(
        "PEX output options",
        "Tailor the behavior of the emitted .pex file if -o is specified.",
    )

    group.add_argument(
        "--include-tools",
        dest="include_tools",
        default=False,
        action=HandleBoolAction,
        help="Whether to include runtime tools in the pex file. If included, these can be run by "
        "exporting PEX_TOOLS=1 and following the usage and --help information.",
    )

    group.add_argument(
        "--zip-safe",
        "--not-zip-safe",
        dest="zip_safe",
        metavar="DEPRECATED",
        default=None,
        action=HandleBoolAction,
        help=(
            "Deprecated: This option is no longer used since user code is now always unzipped "
            "before execution."
        ),
    )
    group.add_argument(
        "--layout",
        dest="layout",
        default=Layout.ZIPAPP,
        choices=Layout.values(),
        type=Layout.for_value,
        help=(
            "By default, a PEX is created as a single file zipapp when `-o` is specified, but "
            "either a packed or loose directory tree based layout can be chosen instead. A packed "
            "layout PEX is an executable directory structure designed to have cache-friendly "
            "characteristics for syncing incremental updates to PEXed applications over a network. "
            "At the top level of the packed directory tree there is an executable `__main__.py`"
            "script. The directory can also be executed by passing its path to a Python "
            "executable; e.g: `python packed-pex-dir/`. The Pex bootstrap code and all dependency "
            "code are packed into individual zip files for efficient caching and syncing. A loose "
            "layout PEX is similar to a packed PEX, except that neither the Pex bootstrap code nor "
            "the dependency code are packed into zip files, but are instead present as collections "
            "of loose files in the directory tree providing different caching and syncing "
            "tradeoffs. Both zipapp and packed layouts install themselves in the PEX_ROOT as loose "
            "apps by default before executing, but these layouts compose with `--venv` execution "
            "mode as well and support `--seed`ing."
        ),
    )

    group.add_argument(
        "--compress",
        "--compressed",
        "--no-compress",
        "--not-compressed",
        "--no-compression",
        dest="compress",
        default=True,
        action=HandleBoolAction,
        help=(
            "Whether to compress zip entries when creating either a zipapp PEX file or a packed "
            "PEX's bootstrap and dependency zip files. Does nothing for loose layout PEXes."
        ),
    )

    runtime_mode = group.add_mutually_exclusive_group()
    runtime_mode.add_argument(
        "--unzip",
        "--no-unzip",
        dest="unzip",
        metavar="DEPRECATED",
        default=None,
        action=HandleBoolAction,
        help=(
            "Deprecated: This option is no longer used since unzipping PEX zip files before "
            "execution is now the default."
        ),
    )
    runtime_mode.add_argument(
        "--venv",
        dest="venv",
        metavar="{prepend,append}",
        default=False,
        action=HandleVenvAction,
        help="Convert the pex file to a venv before executing it. If 'prepend' or 'append' is "
        "specified, then all scripts and console scripts provided by distributions in the pex file "
        "will be added to the PATH in the corresponding position. If the the pex file will be run "
        "multiple times under a stable runtime PEX_ROOT, the venv creation will only be done once "
        "and subsequent runs will enjoy lower startup latency.",
    )
    group.add_argument(
        "--venv-copies",
        "--no-venv-copies",
        dest="venv_copies",
        default=False,
        action=HandleBoolAction,
        help=(
            "If --venv is specified, create the venv using copies of base interpreter files "
            "instead of symlinks. This allows --venv mode PEXes to work across interpreter "
            "upgrades without being forced to remove the PEX_ROOT to allow the venv to re-build "
            "using the upgraded interpreter."
        ),
    )
    group.add_argument(
        "--venv-site-packages-copies",
        "--no-venv-site-packages-copies",
        dest="venv_site_packages_copies",
        default=False,
        action=HandleBoolAction,
        help=(
            "If --venv is specified, populate the venv site packages using hard links or copies of "
            "resolved PEX dependencies instead of symlinks. This can be used to work around "
            "problems with tools or libraries that are confused by symlinked source files."
        ),
    )

    group.add_argument(
        "--always-write-cache",
        dest="always_write_cache",
        default=None,
        action="store_true",
        help=(
            "Deprecated: This option is no longer used; all internally cached distributions in a "
            "PEX are always installed into the local Pex dependency cache."
        ),
    )

    group.add_argument(
        "--ignore-errors",
        dest="ignore_errors",
        default=False,
        action="store_true",
        help="Ignore requirement resolution solver errors when building pexes and later invoking "
        "them.",
    )

    group.add_argument(
        "--inherit-path",
        dest="inherit_path",
        default=InheritPath.FALSE,
        choices=InheritPath.values(),
        type=InheritPath.for_value,
        help="Inherit the contents of sys.path (including site-packages, user site-packages and "
        "PYTHONPATH) running the pex. Possible values: {false} (does not inherit sys.path), "
        "{fallback} (inherits sys.path after packaged dependencies), {prefer} (inherits sys.path "
        "before packaged dependencies), No value (alias for prefer, for backwards "
        "compatibility).".format(
            false=InheritPath.FALSE, fallback=InheritPath.FALLBACK, prefer=InheritPath.PREFER
        ),
    )

    group.add_argument(
        "--compile",
        "--no-compile",
        dest="compile",
        default=False,
        action=HandleBoolAction,
        help="Compiling means that the built pex will include .pyc files, which will result in "
        "slightly faster startup performance. However, compiling means that the generated pex "
        "likely will not be reproducible, meaning that if you were to run `./pex -o` with the "
        "same inputs then the new pex would not be byte-for-byte identical to the original.",
    )

    group.add_argument(
        "--use-system-time",
        "--no-use-system-time",
        dest="use_system_time",
        default=False,
        action=HandleBoolAction,
        help="Use the current system time to generate timestamps for the new pex. Otherwise, Pex "
        "will use midnight on January 1, 1980. By using system time, the generated pex "
        "will not be reproducible, meaning that if you were to run `./pex -o` with the "
        "same inputs then the new pex would not be byte-for-byte identical to the original.",
    )

    group.add_argument(
        "--runtime-pex-root",
        dest="runtime_pex_root",
        default=None,
        help="Specify the pex root to be used in the generated .pex file (if unspecified, "
        "uses ~/.pex).",
    )

    group.add_argument(
        "--strip-pex-env",
        "--no-strip-pex-env",
        dest="strip_pex_env",
        default=True,
        action=HandleBoolAction,
        help="Strip all `PEX_*` environment variables used to control the pex runtime before handing "
        "off control to the pex entrypoint. You might want to set this to `False` if the new "
        "pex executes other pexes (or the Pex CLI itself) and you want the executed pex to be "
        "controllable via `PEX_*` environment variables.",
    )


def configure_clp_pex_environment(parser):
    # type: (ArgumentParser) -> None
    group = parser.add_argument_group(
        "PEX target environment options",
        "Specify which target environments the PEX should run on. If more than one interpreter or "
        "platform is specified, a multi-platform PEX will be created that can run on all specified "
        "targets. N.B.: You may need to adjust the `--python-shebang` so that it works in all "
        "the specified target environments.",
    )

    target_options.register(group)

    group.add_argument(
        "--python-shebang",
        dest="python_shebang",
        default=None,
        help="The exact shebang (#!...) line to add at the top of the PEX file minus the "
        "#!. This overrides the default behavior, which picks an environment Python "
        "interpreter compatible with the one used to build the PEX file.",
    )


def configure_clp_pex_entry_points(parser):
    # type: (ArgumentParser) -> None
    group = parser.add_argument_group(
        "PEX entry point options",
        "Specify what target/module the PEX should invoke if any.",
    )

    group.add_argument(
        "-m",
        "-e",
        "--entry-point",
        dest="entry_point",
        metavar="MODULE[:SYMBOL]",
        default=None,
        help="Set the entry point to module or module:symbol.  If just specifying module, pex "
        "behaves like python -m, e.g. python -m SimpleHTTPServer.  If specifying "
        "module:symbol, pex assume symbol is a n0-arg callable and imports that symbol and invokes "
        "it as if via `sys.exit(symbol())`.",
    )

    group.add_argument(
        "-c",
        "--script",
        "--console-script",
        dest="script",
        default=None,
        metavar="SCRIPT_NAME",
        help="Set the entry point as to the script or console_script as defined by a any of the "
        'distributions in the pex.  For example: "pex -c fab fabric" or "pex -c mturk boto".',
    )

    group.add_argument(
        "--validate-entry-point",
        dest="validate_ep",
        default=False,
        action="store_true",
        help="Validate the entry point by importing it in separate process. Warning: this could have "
        "side effects. For example, entry point `a.b.c:m` will translate to "
        "`from a.b.c import m` during validation.",
    )


class Seed(Enum["Seed.Value"]):
    class Value(Enum.Value):
        pass

    NONE = Value("none")
    ARGS = Value("args")
    VERBOSE = Value("verbose")


class HandleSeedAction(Action):
    def __init__(self, *args, **kwargs):
        kwargs["nargs"] = "?"
        kwargs["choices"] = [seed.value for seed in Seed.values()]
        super(HandleSeedAction, self).__init__(*args, **kwargs)

    def __call__(self, parser, namespace, value, option_str=None):
        seed = Seed.ARGS if value is None else Seed.for_value(value)
        setattr(namespace, self.dest, seed)


def configure_clp():
    # type: () -> ArgumentParser
    usage = (
        "%(prog)s [-o OUTPUT.PEX] [options] [-- arg1 arg2 ...]\n\n"
        "%(prog)s builds a PEX (Python Executable) file based on the given specifications: "
        "sources, requirements, their dependencies and other options."
        "\n"
        "Command-line options can be provided in one or more files by prefixing the filenames "
        "with an @ symbol. These files must contain one argument per line."
    )

    parser = ArgumentParser(
        usage=usage,
        formatter_class=ArgumentDefaultsHelpFormatter,
        fromfile_prefix_chars="@",
    )

    parser.add_argument("-V", "--version", action="version", version=__version__)

    configure_clp_pex_resolution(parser)
    configure_clp_pex_options(parser)
    configure_clp_pex_environment(parser)
    configure_clp_pex_entry_points(parser)

    parser.add_argument(
        "-o",
        "--output-file",
        dest="pex_name",
        default=None,
        help="The name of the generated .pex file: Omitting this will run PEX "
        "immediately and not save it to a file.",
    )

    parser.add_argument(
        "-p",
        "--preamble-file",
        dest="preamble_file",
        metavar="FILE",
        default=None,
        type=str,
        help="The name of a file to be included as the preamble for the generated .pex file",
    )

    parser.add_argument(
        "-D",
        "--sources-directory",
        dest="sources_directory",
        metavar="DIR",
        default=[],
        type=str,
        action="append",
        help=(
            "Add a directory containing sources and/or resources to be packaged into the generated "
            ".pex file. This option can be used multiple times."
        ),
    )

    parser.add_argument(
        "-R",
        "--resources-directory",
        dest="resources_directory",
        metavar="DIR",
        default=[],
        type=str,
        action="append",
        help=(
            "Add resources directory to be packaged into the generated .pex file."
            " This option can be used multiple times. DEPRECATED: Use -D/--sources-directory "
            "instead."
        ),
    )

    requirement_options.register(parser)

    parser.add_argument(
        "--requirements-pex",
        dest="requirements_pexes",
        metavar="FILE",
        default=[],
        type=str,
        action="append",
        help="Add requirements from the given .pex file.  This option can be used multiple times.",
    )

    register_global_arguments(parser, include_verbosity=True)

    parser.add_argument(
        "--seed",
        dest="seed",
        action=HandleSeedAction,
        default=Seed.NONE,
        help=(
            "Seed local Pex caches for the generated PEX and print out the command line to run "
            "directly from the seed with ({args}) or else a json object including the 'pex_root' "
            "path, the 'python' binary path and the seeded 'pex' path ({seed}).".format(
                args=Seed.ARGS, seed=Seed.VERBOSE
            )
        ),
    )
    parser.add_argument(
        "--no-seed",
        dest="seed",
        action="store_const",
        const=Seed.NONE,
        metavar="DEPRECATED",
        help="Deprecated: Use --seed=none instead.",
    )

    parser.add_argument(
        "--help-variables",
        action=PrintVariableHelpAction,
        nargs=0,
        help="Print out help about the various environment variables used to change the behavior of "
        "a running PEX file.",
    )

    return parser


def build_pex(
    requirement_configuration,  # type: RequirementConfiguration
    resolver_configuration,  # type: ResolverConfiguration
    targets,  # type: Targets
    options,  # type: Namespace
    cache=None,  # type: Optional[str]
):
    # type: (...) -> PEXBuilder

    preamble = None  # type: Optional[str]
    if options.preamble_file:
        with open(options.preamble_file) as preamble_fd:
            preamble = preamble_fd.read()

    pex_builder = PEXBuilder(
        path=safe_mkdtemp(),
        interpreter=targets.interpreter,
        preamble=preamble,
        copy_mode=CopyMode.SYMLINK,
    )

    if options.resources_directory:
        pex_warnings.warn(
            "The `-R/--resources-directory` option is deprecated. Resources should be added via "
            "`-D/--sources-directory` instead."
        )

    if options.zip_safe is not None:
        pex_warnings.warn(
            "The `--zip-safe/--not-zip-safe` option is deprecated. This option is no longer used "
            "since user code is now always unzipped before execution."
        )

    if options.unzip is not None:
        pex_warnings.warn(
            "The `--unzip/--no-unzip` option is deprecated. This option is no longer used since "
            "unzipping PEX zip files before execution is now the default."
        )

    if options.always_write_cache is not None:
        pex_warnings.warn(
            "The `--always-write-cache` option is deprecated. This option is no longer used; all "
            "internally cached distributions in a PEX are always installed into the local Pex "
            "dependency cache."
        )

    directories = OrderedSet(
        options.sources_directory + options.resources_directory
    )  # type: OrderedSet[str]
    for directory in directories:
        src_dir = os.path.normpath(directory)
        for root, _, files in os.walk(src_dir):
            for f in files:
                src_file_path = os.path.join(root, f)
                dst_path = os.path.relpath(src_file_path, src_dir)
                pex_builder.add_source(src_file_path, dst_path)

    pex_info = pex_builder.info
    pex_info.venv = bool(options.venv)
    pex_info.venv_bin_path = options.venv or BinPath.FALSE
    pex_info.venv_copies = options.venv_copies
    pex_info.venv_site_packages_copies = options.venv_site_packages_copies
    pex_info.includes_tools = options.include_tools or options.venv
    pex_info.pex_path = options.pex_path
    pex_info.ignore_errors = options.ignore_errors
    pex_info.emit_warnings = options.emit_warnings
    pex_info.inherit_path = options.inherit_path
    pex_info.pex_root = options.runtime_pex_root
    pex_info.strip_pex_env = options.strip_pex_env

    if options.interpreter_constraint:
        for ic in options.interpreter_constraint:
            pex_builder.add_interpreter_constraint(ic)

    for requirements_pex in options.requirements_pexes:
        pex_builder.add_from_requirements_pex(requirements_pex)

    with TRACER.timed(
        "Resolving distributions ({})".format(
            " ".join(
                itertools.chain.from_iterable(
                    (
                        requirement_configuration.requirements or (),
                        requirement_configuration.requirement_files or (),
                    )
                )
            )
        )
    ):
        try:
            if isinstance(resolver_configuration, LockRepositoryConfiguration):
                with TRACER.timed(
                    "Resolving requirements from lock file {lock_file}".format(
                        lock_file=resolver_configuration.lock_file
                    )
                ):
                    pip_configuration = resolver_configuration.pip_configuration
                    result = try_(
                        resolve_from_lock(
                            targets=targets,
                            lockfile_path=resolver_configuration.lock_file,
                            requirements=requirement_configuration.requirements,
                            requirement_files=requirement_configuration.requirement_files,
                            constraint_files=requirement_configuration.constraint_files,
                            transitive=pip_configuration.transitive,
                            indexes=pip_configuration.repos_configuration.indexes,
                            find_links=pip_configuration.repos_configuration.find_links,
                            resolver_version=pip_configuration.resolver_version,
                            network_configuration=pip_configuration.network_configuration,
                            cache=cache,
                            build=pip_configuration.allow_builds,
                            use_wheel=pip_configuration.allow_wheels,
                            prefer_older_binary=pip_configuration.prefer_older_binary,
                            use_pep517=pip_configuration.use_pep517,
                            build_isolation=pip_configuration.build_isolation,
                            compile=options.compile,
                            max_parallel_jobs=pip_configuration.max_jobs,
                        )
                    )
            elif isinstance(resolver_configuration, PexRepositoryConfiguration):
                with TRACER.timed(
                    "Resolving requirements from PEX {pex_repository}.".format(
                        pex_repository=resolver_configuration.pex_repository
                    )
                ):
                    result = resolve_from_pex(
                        targets=targets,
                        pex=resolver_configuration.pex_repository,
                        requirements=requirement_configuration.requirements,
                        requirement_files=requirement_configuration.requirement_files,
                        constraint_files=requirement_configuration.constraint_files,
                        network_configuration=resolver_configuration.network_configuration,
                        transitive=resolver_configuration.transitive,
                        ignore_errors=options.ignore_errors,
                    )
            else:
                with TRACER.timed("Resolving requirements."):
                    result = resolve(
                        targets=targets,
                        requirements=requirement_configuration.requirements,
                        requirement_files=requirement_configuration.requirement_files,
                        constraint_files=requirement_configuration.constraint_files,
                        allow_prereleases=resolver_configuration.allow_prereleases,
                        transitive=resolver_configuration.transitive,
                        indexes=resolver_configuration.repos_configuration.indexes,
                        find_links=resolver_configuration.repos_configuration.find_links,
                        resolver_version=resolver_configuration.resolver_version,
                        network_configuration=resolver_configuration.network_configuration,
                        cache=cache,
                        build=resolver_configuration.allow_builds,
                        use_wheel=resolver_configuration.allow_wheels,
                        prefer_older_binary=resolver_configuration.prefer_older_binary,
                        use_pep517=resolver_configuration.use_pep517,
                        build_isolation=resolver_configuration.build_isolation,
                        compile=options.compile,
                        max_parallel_jobs=resolver_configuration.max_jobs,
                        ignore_errors=options.ignore_errors,
                    )

            for installed_dist in result.installed_distributions:
                pex_builder.add_distribution(
                    installed_dist.distribution, fingerprint=installed_dist.fingerprint
                )
                for direct_req in installed_dist.direct_requirements:
                    pex_builder.add_requirement(direct_req)
        except Unsatisfiable as e:
            die(str(e))

    if options.entry_point and options.script:
        die("Must specify at most one entry point or script.", INVALID_OPTIONS)

    if options.entry_point:
        pex_builder.set_entry_point(options.entry_point)
    elif options.script:
        pex_builder.set_script(options.script)

    if options.python_shebang:
        pex_builder.set_shebang(options.python_shebang)

    return pex_builder


def transform_legacy_arg(arg):
    # type: (str) -> str
    # inherit-path used to be a boolean arg (so either was absent, or --inherit-path)
    # Now it takes a string argument, so --inherit-path is invalid.
    # Fix up the args we're about to parse to preserve backwards compatibility.
    if arg == "--inherit-path":
        return "--inherit-path={}".format(InheritPath.PREFER.value)
    return arg


def _compatible_with_current_platform(interpreter, platforms):
    if not platforms:
        return True
    current_platforms = set(interpreter.supported_platforms)
    current_platforms.add(None)
    return current_platforms.intersection(platforms)


def main(args=None):
    args = args[:] if args else sys.argv[1:]
    args = [transform_legacy_arg(arg) for arg in args]
    parser = configure_clp()

    try:
        separator = args.index("--")
        args, cmdline = args[:separator], args[separator + 1 :]
    except ValueError:
        args, cmdline = args, []

    options = parser.parse_args(args=args)
    try:
        with global_environment(options) as env:
            requirement_configuration = requirement_options.configure(options)

            try:
                resolver_configuration = resolver_options.configure(options)
            except resolver_options.InvalidConfigurationError as e:
                die(str(e))

            try:
                targets = target_options.configure(options).resolve_targets()
            except target_configuration.InterpreterNotFound as e:
                die(str(e))
            except target_configuration.InterpreterConstraintsNotSatisfied as e:
                die(str(e), exit_code=CANNOT_SETUP_INTERPRETER)

            do_main(
                options=options,
                requirement_configuration=requirement_configuration,
                resolver_configuration=resolver_configuration,
                targets=targets,
                cmdline=cmdline,
                env=env,
            )
    except GlobalConfigurationError as e:
        die(str(e))


def do_main(
    options,  # type: Namespace
    requirement_configuration,  # type: RequirementConfiguration
    resolver_configuration,  # type: ResolverConfiguration
    targets,  # type: Targets
    cmdline,  # type: List[str]
    env,  # type: Dict[str, str]
):
    with TRACER.timed("Building pex"):
        pex_builder = build_pex(
            requirement_configuration=requirement_configuration,
            resolver_configuration=resolver_configuration,
            targets=targets,
            options=options,
            cache=ENV.PEX_ROOT,
        )

    pex_builder.freeze(bytecode_compile=options.compile)
    interpreter = pex_builder.interpreter
    pex = PEX(
        pex_builder.path(),
        interpreter=interpreter,
        verify_entry_point=options.validate_ep,
    )

    if options.pex_name is not None:
        log("Saving PEX file to %s" % options.pex_name, V=options.verbosity)
        pex_builder.build(
            options.pex_name,
            bytecode_compile=options.compile,
            deterministic_timestamp=not options.use_system_time,
            layout=options.layout,
            compress=options.compress,
        )
        if options.seed != Seed.NONE:
            seed_info = seed_cache(options, pex, verbose=options.seed == Seed.VERBOSE)
            print(seed_info)
    else:
        if not _compatible_with_current_platform(interpreter, targets.platforms):
            log("WARNING: attempting to run PEX with incompatible platforms!", V=1)
            log(
                "Running on platform {} but built for {}".format(
                    interpreter.platform, ", ".join(map(str, targets.platforms))
                ),
                V=1,
            )

        log(
            "Running PEX file at %s with args %s" % (pex_builder.path(), cmdline),
            V=options.verbosity,
        )
        sys.exit(pex.run(args=list(cmdline), env=env))


def seed_cache(
    options,  # type: Namespace
    pex,  # type: PEX
    verbose=False,  # type : bool
):
    # type: (...) -> str

    pex_path = cast(str, options.pex_name)
    with TRACER.timed("Seeding local caches for {}".format(pex_path)):
        pex_info = pex.pex_info()
        pex_root = pex_info.pex_root

        def create_verbose_info(final_pex_path):
            # type: (str) -> Dict[str, str]
            return dict(pex_root=pex_root, python=pex.interpreter.binary, pex=final_pex_path)

        if options.venv:
            with TRACER.timed("Creating venv from {}".format(pex_path)):
                with ENV.patch(PEX=os.path.realpath(os.path.expanduser(pex_path))):
                    venv_pex = ensure_venv(pex)
                    if verbose:
                        return json.dumps(create_verbose_info(final_pex_path=venv_pex))
                    else:
                        return venv_pex

        pex_hash = pex_info.pex_hash
        if pex_hash is None:
            raise AssertionError(
                "There was no pex_hash stored in {} for {}.".format(PexInfo.PATH, pex_path)
            )

        with TRACER.timed("Seeding caches for {}".format(pex_path)):
            final_pex_path = os.path.join(
                maybe_install(pex=pex_path, pex_root=pex_root, pex_hash=pex_hash)
                or os.path.abspath(pex_path),
                "__main__.py",
            )
            if verbose:
                return json.dumps(create_verbose_info(final_pex_path=final_pex_path))
            else:
                return final_pex_path


if __name__ == "__main__":
    main()
