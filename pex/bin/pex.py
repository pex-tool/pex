# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""
The pex.bin.pex utility builds PEX environments and .pex files specified by
sources, requirements and their dependencies.
"""

from __future__ import absolute_import, print_function

import os
import sys
import tempfile
from optparse import OptionGroup, OptionParser, OptionValueError
from textwrap import TextWrapper

from pex import pex_warnings
from pex.common import die, safe_delete, safe_mkdtemp
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import (
    UnsatisfiableInterpreterConstraintsError,
    validate_constraints,
)
from pex.jobs import DEFAULT_MAX_JOBS
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pex import PEX
from pex.pex_bootstrapper import iter_compatible_interpreters
from pex.pex_builder import PEXBuilder
from pex.platforms import Platform
from pex.resolver import Unsatisfiable, parsed_platform, resolve_multi
from pex.tracer import TRACER
from pex.variables import ENV, Variables
from pex.version import __version__

CANNOT_SETUP_INTERPRETER = 102
INVALID_OPTIONS = 103


def log(msg, V=0):
    if V != 0:
        print(msg, file=sys.stderr)


def parse_bool(option, opt_str, _, parser):
    setattr(parser.values, option.dest, not opt_str.startswith("--no"))


def increment_verbosity(option, opt_str, _, parser):
    verbosity = getattr(parser.values, option.dest, 0)
    setattr(parser.values, option.dest, verbosity + 1)


def process_disable_cache(option, option_str, option_value, parser):
    setattr(parser.values, option.dest, None)


class PyPiSentinel(object):
    def __str__(self):
        return "https://pypi.org/simple"


_PYPI = PyPiSentinel()


def process_pypi_option(option, option_str, option_value, parser):
    if option_str.startswith("--no"):
        setattr(parser.values, option.dest, [])
    else:
        indexes = getattr(parser.values, option.dest, [])
        if _PYPI not in indexes:
            indexes.append(_PYPI)
        setattr(parser.values, option.dest, indexes)


def process_find_links(option, option_str, option_value, parser):
    find_links = getattr(parser.values, option.dest, [])
    if option_value not in find_links:
        find_links.append(option_value)
    setattr(parser.values, option.dest, find_links)


def process_index_url(option, option_str, option_value, parser):
    indexes = getattr(parser.values, option.dest, [])
    if option_value not in indexes:
        indexes.append(option_value)
    setattr(parser.values, option.dest, indexes)


_DEFAULT_MANYLINUX_STANDARD = "manylinux2014"


def process_manylinux(option, option_str, option_value, parser):
    if option_str.startswith("--no"):
        setattr(parser.values, option.dest, None)
    elif option_value.startswith("manylinux"):
        setattr(parser.values, option.dest, option_value)
    else:
        raise OptionValueError(
            "Please specify a manylinux standard; ie: --manylinux=manylinux1. "
            "Given {}".format(option_value)
        )


def process_transitive(option, option_str, option_value, parser):
    transitive = option_str == "--transitive"
    setattr(parser.values, option.dest, transitive)


def print_variable_help(option, option_str, option_value, parser):
    for variable_name, variable_type, variable_help in Variables.iter_help():
        print("\n%s: %s\n" % (variable_name, variable_type))
        for line in TextWrapper(initial_indent=" " * 4, subsequent_indent=" " * 4).wrap(
            variable_help
        ):
            print(line)
    sys.exit(0)


def process_platform(option, option_str, option_value, parser):
    platforms = getattr(parser.values, option.dest, [])
    try:
        platforms.append(parsed_platform(option_value))
    except Platform.InvalidPlatformError as e:
        raise OptionValueError("The {} option is invalid:\n{}".format(option_str, e))


def configure_clp_pex_resolution(parser):
    # type: (OptionParser) -> None
    group = OptionGroup(
        parser,
        "Resolver options",
        "Tailor how to find, resolve and translate the packages that get put into the PEX "
        "environment.",
    )

    group.add_option(
        "--pypi",
        "--no-pypi",
        "--no-index",
        action="callback",
        dest="indexes",
        default=[_PYPI],
        callback=process_pypi_option,
        help="Whether to use pypi to resolve dependencies; Default: use pypi",
    )

    group.add_option(
        "--pex-path",
        dest="pex_path",
        type=str,
        default=None,
        help="A colon separated list of other pex files to merge into the runtime environment.",
    )

    group.add_option(
        "-f",
        "--find-links",
        "--repo",
        metavar="PATH/URL",
        action="callback",
        default=[],
        dest="find_links",
        callback=process_find_links,
        type=str,
        help="Additional repository path (directory or URL) to look for requirements.",
    )

    group.add_option(
        "-i",
        "--index",
        "--index-url",
        metavar="URL",
        action="callback",
        dest="indexes",
        callback=process_index_url,
        type=str,
        help="Additional cheeseshop indices to use to satisfy requirements.",
    )

    default_net_config = NetworkConfiguration.create()

    group.add_option(
        "--cache-ttl",
        metavar="SECS",
        default=default_net_config.cache_ttl,
        type=int,
        help="Set the maximum age of items in the HTTP cache in seconds. [Default: %default]",
    )

    group.add_option(
        "--retries",
        default=default_net_config.retries,
        type=int,
        help="Maximum number of retries each connection should attempt. [Default: %default]",
    )

    group.add_option(
        "--timeout",
        metavar="SECS",
        default=default_net_config.timeout,
        type=int,
        help="Set the socket timeout in seconds. [Default: %default]",
    )

    group.add_option(
        "-H",
        "--header",
        dest="headers",
        metavar="NAME:VALUE",
        default=[],
        type=str,
        action="append",
        help="Additional HTTP headers to include in all requests.",
    )

    group.add_option(
        "--proxy",
        type=str,
        default=None,
        help="Specify a proxy in the form [user:passwd@]proxy.server:port.",
    )

    group.add_option(
        "--cert", metavar="PATH", type=str, default=None, help="Path to alternate CA bundle."
    )

    group.add_option(
        "--client-cert",
        metavar="PATH",
        type=str,
        default=None,
        help="Path to an SSL client certificate which should be a single file containing the private "
        "key and the certificate in PEM format.",
    )

    group.add_option(
        "--pre",
        "--no-pre",
        dest="allow_prereleases",
        default=False,
        action="callback",
        callback=parse_bool,
        help="Whether to include pre-release and development versions of requirements; "
        "Default: only stable versions are used, unless explicitly requested",
    )

    group.add_option(
        "--disable-cache",
        dest="disable_cache",
        default=False,
        action="store_true",
        help="Disable caching in the pex tool entirely.",
    )

    group.add_option(
        "--cache-dir",
        dest="cache_dir",
        default=None,
        help="DEPRECATED: Use --pex-root instead. "
        "The local cache directory to use for speeding up requirement "
        "lookups. [Default: {}]".format(ENV.PEX_ROOT),
    )

    group.add_option(
        "--wheel",
        "--no-wheel",
        "--no-use-wheel",
        dest="use_wheel",
        default=True,
        action="callback",
        callback=parse_bool,
        help="Whether to allow wheel distributions; Default: allow wheels",
    )

    group.add_option(
        "--build",
        "--no-build",
        dest="build",
        default=True,
        action="callback",
        callback=parse_bool,
        help="Whether to allow building of distributions from source; Default: allow builds",
    )

    group.add_option(
        "--manylinux",
        "--no-manylinux",
        "--no-use-manylinux",
        dest="manylinux",
        type=str,
        default=_DEFAULT_MANYLINUX_STANDARD,
        action="callback",
        callback=process_manylinux,
        help=(
            "Whether to allow resolution of manylinux wheels for linux target "
            "platforms; Default: allow manylinux wheels compatible with {}".format(
                _DEFAULT_MANYLINUX_STANDARD
            )
        ),
    )

    group.add_option(
        "--transitive",
        "--no-transitive",
        "--intransitive",
        dest="transitive",
        default=True,
        action="callback",
        callback=process_transitive,
        help="Whether to transitively resolve requirements. Default: True",
    )

    group.add_option(
        "-j",
        "--jobs",
        metavar="JOBS",
        dest="max_parallel_jobs",
        type=int,
        default=DEFAULT_MAX_JOBS,
        help="The maximum number of parallel jobs to use when resolving, building and installing "
        "distributions. You might want to increase the maximum number of parallel jobs to "
        "potentially improve the latency of the pex creation process at the expense of other"
        "processes on your system. [Default: %default]",
    )

    parser.add_option_group(group)


def configure_clp_pex_options(parser):
    # type: (OptionParser) -> None
    group = OptionGroup(
        parser,
        "PEX output options",
        "Tailor the behavior of the emitted .pex file if -o is specified.",
    )

    group.add_option(
        "--zip-safe",
        "--not-zip-safe",
        dest="zip_safe",
        default=True,
        action="callback",
        callback=parse_bool,
        help="Whether or not the sources in the pex file are zip safe.  If they are not zip safe, "
        "they will be written to disk prior to execution. Also see --unzip which will cause the "
        "complete pex file, including dependencies, to be unzipped."
        "[Default: zip safe.]",
    )

    group.add_option(
        "--unzip",
        "--no-unzip",
        dest="unzip",
        default=False,
        action="callback",
        callback=parse_bool,
        help="Whether or not the pex file should be unzipped before executing it. If the pex file will "
        "be run multiple times under a stable runtime PEX_ROOT the unzipping will only be "
        "performed once and subsequent runs will enjoy lower startup latency. "
        "[Default: do not unzip.]",
    )

    group.add_option(
        "--always-write-cache",
        dest="always_write_cache",
        default=False,
        action="store_true",
        help="Always write the internally cached distributions to disk prior to invoking "
        "the pex source code.  This can use less memory in RAM constrained "
        "environments. [Default: %default]",
    )

    group.add_option(
        "--ignore-errors",
        dest="ignore_errors",
        default=False,
        action="store_true",
        help="Ignore requirement resolution solver errors when building pexes and later invoking "
        "them. [Default: %default]",
    )

    group.add_option(
        "--inherit-path",
        dest="inherit_path",
        default="false",
        action="store",
        choices=["false", "fallback", "prefer"],
        help="Inherit the contents of sys.path (including site-packages, user site-packages and "
        "PYTHONPATH) running the pex. Possible values: false (does not inherit sys.path), "
        "fallback (inherits sys.path after packaged dependencies), prefer (inherits sys.path "
        "before packaged dependencies), No value (alias for prefer, for backwards "
        "compatibility). [Default: %default]",
    )

    group.add_option(
        "--compile",
        "--no-compile",
        dest="compile",
        default=False,
        action="callback",
        callback=parse_bool,
        help="Compiling means that the built pex will include .pyc files, which will result in "
        "slightly faster startup performance. However, compiling means that the generated pex "
        "likely will not be reproducible, meaning that if you were to run `./pex -o` with the "
        "same inputs then the new pex would not be byte-for-byte identical to the original.",
    )

    group.add_option(
        "--use-system-time",
        "--no-use-system-time",
        dest="use_system_time",
        default=False,
        action="callback",
        callback=parse_bool,
        help="Use the current system time to generate timestamps for the new pex. Otherwise, Pex "
        "will use midnight on January 1, 1980. By using system time, the generated pex "
        "will not be reproducible, meaning that if you were to run `./pex -o` with the "
        "same inputs then the new pex would not be byte-for-byte identical to the original.",
    )

    group.add_option(
        "--runtime-pex-root",
        dest="runtime_pex_root",
        default=None,
        help="Specify the pex root to be used in the generated .pex file. [Default: ~/.pex]",
    )

    group.add_option(
        "--strip-pex-env",
        "--no-strip-pex-env",
        dest="strip_pex_env",
        default=True,
        action="callback",
        callback=parse_bool,
        help="Strip all `PEX_*` environment variables used to control the pex runtime before handing "
        "off control to the pex entrypoint. You might want to set this to `False` if the new "
        "pex executes other pexes (or the Pex CLI itself and you want the executed pex to be "
        "controllable via `PEX_*` environment variables. [Default: %default]",
    )

    parser.add_option_group(group)


def configure_clp_pex_environment(parser):
    # type: (OptionParser) -> None
    group = OptionGroup(
        parser,
        "PEX environment options",
        "Tailor the interpreter and platform targets for the PEX environment.",
    )

    group.add_option(
        "--python",
        dest="python",
        default=[],
        type="str",
        action="append",
        help="The Python interpreter to use to build the pex.  Either specify an explicit "
        "path to an interpreter, or specify a binary accessible on $PATH. This option "
        "can be passed multiple times to create a multi-interpreter compatible pex. "
        "Default: Use current interpreter.",
    )

    group.add_option(
        "--interpreter-constraint",
        dest="interpreter_constraint",
        default=[],
        type="str",
        action="append",
        help="Constrain the selected Python interpreter. Specify with Requirement-style syntax, "
        'e.g. "CPython>=2.7,<3" (A CPython interpreter with version >=2.7 AND version <3) '
        'or "PyPy" (A pypy interpreter of any version). This argument may be repeated multiple '
        "times to OR the constraints.",
    )

    group.add_option(
        "--rcfile",
        dest="rc_file",
        default=None,
        help="An additional path to a pexrc file to read during configuration parsing. "
        "Used primarily for testing.",
    )

    group.add_option(
        "--python-shebang",
        dest="python_shebang",
        default=None,
        help="The exact shebang (#!...) line to add at the top of the PEX file minus the "
        "#!. This overrides the default behavior, which picks an environment Python "
        "interpreter compatible with the one used to build the PEX file.",
    )

    current_interpreter = PythonInterpreter.get()
    group.add_option(
        "--platform",
        dest="platforms",
        default=[],
        type=str,
        action="callback",
        callback=process_platform,
        help="The platform for which to build the PEX. This option can be passed multiple times "
        "to create a multi-platform pex. To use the platform corresponding to the current "
        "interpreter you can pass `current`. To target any other platform you pass a string "
        "composed of fields: <platform>-<python impl abbr>-<python version>-<abi>. "
        "These fields stem from wheel name conventions as outlined in "
        "https://www.python.org/dev/peps/pep-0427#file-name-convention and influenced by "
        "https://www.python.org/dev/peps/pep-0425. For the current interpreter at {} the full "
        "platform string is {}. To find out more, try `{} --platform explain`.".format(
            current_interpreter.binary, current_interpreter.platform, sys.argv[0]
        ),
    )

    group.add_option(
        "--resolve-local-platforms",
        dest="resolve_local_platforms",
        default=False,
        action="callback",
        callback=parse_bool,
        help="When --platforms are specified, attempt to resolve a local interpreter that matches "
        "each platform specified. If found, use the interpreter to resolve distributions; if "
        "not (or if this option is not specified), resolve for each platform only allowing "
        "matching binary distributions and failing if only sdists or non-matching binary "
        "distributions can be found.",
    )

    group.add_option(
        "--use-first-matching-interpreter",
        dest="use_first_matching_interpreter",
        default=False,
        action="callback",
        callback=parse_bool,
        help=(
            "If multiple interpreters are valid, use the first one, which is the minimum "
            "compatible Python version. Normally, when multiple interpreters match, Pex will "
            "resolve requirements for each interpreter; this allows the resulting Pex to be "
            "compatible with more interpreters, such as different Python versions. However, "
            "resolving for multiple interpreters will take longer to build, and the resulting PEX "
            "may be larger."
        ),
    )

    parser.add_option_group(group)


def configure_clp_pex_entry_points(parser):
    # type: (OptionParser) -> None
    group = OptionGroup(
        parser,
        "PEX entry point options",
        "Specify what target/module the PEX should invoke if any.",
    )

    group.add_option(
        "-m",
        "-e",
        "--entry-point",
        dest="entry_point",
        metavar="MODULE[:SYMBOL]",
        default=None,
        help="Set the entry point to module or module:symbol.  If just specifying module, pex "
        "behaves like python -m, e.g. python -m SimpleHTTPServer.  If specifying "
        "module:symbol, pex imports that symbol and invokes it as if it were main.",
    )

    group.add_option(
        "-c",
        "--script",
        "--console-script",
        dest="script",
        default=None,
        metavar="SCRIPT_NAME",
        help="Set the entry point as to the script or console_script as defined by a any of the "
        'distributions in the pex.  For example: "pex -c fab fabric" or "pex -c mturk boto".',
    )

    group.add_option(
        "--validate-entry-point",
        dest="validate_ep",
        default=False,
        action="store_true",
        help="Validate the entry point by importing it in separate process. Warning: this could have "
        "side effects. For example, entry point `a.b.c:m` will translate to "
        "`from a.b.c import m` during validation. [Default: %default]",
    )

    parser.add_option_group(group)


def configure_clp():
    # type: () -> OptionParser
    usage = (
        "%prog [-o OUTPUT.PEX] [options] [-- arg1 arg2 ...]\n\n"
        "%prog builds a PEX (Python Executable) file based on the given specifications: "
        "sources, requirements, their dependencies and other options."
    )

    parser = OptionParser(usage=usage, version="%prog {}".format(__version__))
    configure_clp_pex_resolution(parser)
    configure_clp_pex_options(parser)
    configure_clp_pex_environment(parser)
    configure_clp_pex_entry_points(parser)

    parser.add_option(
        "-o",
        "--output-file",
        dest="pex_name",
        default=None,
        help="The name of the generated .pex file: Omitting this will run PEX "
        "immediately and not save it to a file.",
    )

    parser.add_option(
        "-p",
        "--preamble-file",
        dest="preamble_file",
        metavar="FILE",
        default=None,
        type=str,
        help="The name of a file to be included as the preamble for the generated .pex file",
    )

    parser.add_option(
        "-D",
        "--sources-directory",
        dest="sources_directory",
        metavar="DIR",
        default=[],
        type=str,
        action="append",
        help="Add sources directory to be packaged into the generated .pex file."
        "  This option can be used multiple times.",
    )

    parser.add_option(
        "-R",
        "--resources-directory",
        dest="resources_directory",
        metavar="DIR",
        default=[],
        type=str,
        action="append",
        help="Add resources directory to be packaged into the generated .pex file."
        "  This option can be used multiple times.",
    )

    parser.add_option(
        "-r",
        "--requirement",
        dest="requirement_files",
        metavar="FILE",
        default=[],
        type=str,
        action="append",
        help="Add requirements from the given requirements file.  This option can be used multiple "
        "times.",
    )

    parser.add_option(
        "--constraints",
        dest="constraint_files",
        metavar="FILE",
        default=[],
        type=str,
        action="append",
        help="Add constraints from the given constraints file.  This option can be used multiple "
        "times.",
    )

    parser.add_option(
        "--requirements-pex",
        dest="requirements_pexes",
        metavar="FILE",
        default=[],
        type=str,
        action="append",
        help="Add requirements from the given .pex file.  This option can be used multiple times.",
    )

    parser.add_option(
        "-v",
        dest="verbosity",
        default=0,
        action="callback",
        callback=increment_verbosity,
        help="Turn on logging verbosity, may be specified multiple times.",
    )

    parser.add_option(
        "--emit-warnings",
        "--no-emit-warnings",
        dest="emit_warnings",
        action="callback",
        callback=parse_bool,
        default=True,
        help="Emit runtime UserWarnings on stderr. If false, only emit them when PEX_VERBOSE is set."
        "Default: emit user warnings to stderr",
    )

    parser.add_option(
        "--pex-root",
        dest="pex_root",
        default=None,
        help="Specify the pex root used in this invocation of pex. "
        "[Default: {}]".format(ENV.PEX_ROOT),
    )

    parser.add_option(
        "--tmpdir",
        dest="tmpdir",
        default=tempfile.gettempdir(),
        help="Specify the temporary directory Pex and its subprocesses should use. "
        "[Default: %default]",
    )

    parser.add_option(
        "--help-variables",
        action="callback",
        callback=print_variable_help,
        help="Print out help about the various environment variables used to change the behavior of "
        "a running PEX file.",
    )

    return parser


def _safe_link(src, dst):
    try:
        os.unlink(dst)
    except OSError:
        pass
    os.symlink(src, dst)


def build_pex(reqs, options, cache=None):
    interpreters = None  # Default to the current interpreter.

    pex_python_path = None  # Defaults to $PATH
    if options.rc_file or not ENV.PEX_IGNORE_RCFILES:
        rc_variables = Variables(rc=options.rc_file)
        pex_python_path = rc_variables.PEX_PYTHON_PATH

    # NB: options.python and interpreter constraints cannot be used together.
    if options.python:
        with TRACER.timed("Resolving interpreters", V=2):

            def to_python_interpreter(full_path_or_basename):
                if os.path.isfile(full_path_or_basename):
                    return PythonInterpreter.from_binary(full_path_or_basename)
                else:
                    interpreter = PythonInterpreter.from_env(full_path_or_basename)
                    if interpreter is None:
                        die("Failed to find interpreter: %s" % full_path_or_basename)
                    return interpreter

            interpreters = [to_python_interpreter(interp) for interp in options.python]
    elif options.interpreter_constraint:
        with TRACER.timed("Resolving interpreters", V=2):
            constraints = options.interpreter_constraint
            validate_constraints(constraints)
            try:
                interpreters = list(
                    iter_compatible_interpreters(
                        path=pex_python_path, interpreter_constraints=constraints
                    )
                )
            except UnsatisfiableInterpreterConstraintsError as e:
                die(
                    e.create_message("Could not find a compatible interpreter."),
                    CANNOT_SETUP_INTERPRETER,
                )

    platforms = OrderedSet(options.platforms)
    interpreters = interpreters or []
    if options.platforms and options.resolve_local_platforms:
        with TRACER.timed(
            "Searching for local interpreters matching {}".format(", ".join(map(str, platforms)))
        ):
            candidate_interpreters = OrderedSet(iter_compatible_interpreters(path=pex_python_path))
            candidate_interpreters.add(PythonInterpreter.get())
            for candidate_interpreter in candidate_interpreters:
                resolved_platforms = candidate_interpreter.supported_platforms.intersection(
                    platforms
                )
                if resolved_platforms:
                    for resolved_platform in resolved_platforms:
                        TRACER.log(
                            "Resolved {} for platform {}".format(
                                candidate_interpreter, resolved_platform
                            )
                        )
                        platforms.remove(resolved_platform)
                    interpreters.append(candidate_interpreter)
        if platforms:
            TRACER.log(
                "Could not resolve a local interpreter for {}, will resolve only binary distributions "
                "for {}.".format(
                    ", ".join(map(str, platforms)),
                    "this platform" if len(platforms) == 1 else "these platforms",
                )
            )

    interpreter = min(interpreters) if interpreters else None
    if options.use_first_matching_interpreter and interpreters:
        if len(interpreters) > 1:
            unused_interpreters = set(interpreters) - {interpreter}
            TRACER.log(
                "Multiple interpreters resolved, but only using {} because "
                "`--use-first-matching-interpreter` was used. These interpreters were matched but "
                "will not be used: {}".format(
                    interpreter.binary,
                    ", ".join(interpreter.binary for interpreter in sorted(unused_interpreters)),
                )
            )
        interpreters = [interpreter]

    try:
        with open(options.preamble_file) as preamble_fd:
            preamble = preamble_fd.read()
    except TypeError:
        # options.preamble_file is None
        preamble = None

    pex_builder = PEXBuilder(path=safe_mkdtemp(), interpreter=interpreter, preamble=preamble)

    def walk_and_do(fn, src_dir):
        src_dir = os.path.normpath(src_dir)
        for root, dirs, files in os.walk(src_dir):
            for f in files:
                src_file_path = os.path.join(root, f)
                dst_path = os.path.relpath(src_file_path, src_dir)
                fn(src_file_path, dst_path)

    for directory in options.sources_directory:
        walk_and_do(pex_builder.add_source, directory)

    for directory in options.resources_directory:
        walk_and_do(pex_builder.add_resource, directory)

    pex_info = pex_builder.info
    pex_info.zip_safe = options.zip_safe
    pex_info.unzip = options.unzip
    pex_info.pex_path = options.pex_path
    pex_info.always_write_cache = options.always_write_cache
    pex_info.ignore_errors = options.ignore_errors
    pex_info.emit_warnings = options.emit_warnings
    pex_info.inherit_path = options.inherit_path
    pex_info.pex_root = options.runtime_pex_root
    pex_info.strip_pex_env = options.strip_pex_env

    # If we're only building the PEX for the first of many interpreters due to
    # `--use-first-matching-interpreter` selection, we do not want to enable those same interpreter
    # constraints at runtime, where they could lead to a different interpreter being selected
    # leading to a failure to execute the PEX. Instead we rely on the shebang set by that single
    # interpreter to pick out a similar interpreter at runtime (for a CPython interpreter, the
    # shebang will be `#!/usr/bin/env pythonX.Y` which should generally be enough to select a
    # matching interpreter. To be clear though, there are many corners this will not work for
    # including mismatching abi (python2.7m vs python2.7mu) when the PEX contains platform specific
    # wheels, etc.
    if options.interpreter_constraint and not options.use_first_matching_interpreter:
        for ic in options.interpreter_constraint:
            pex_builder.add_interpreter_constraint(ic)

    # NB: `None` means use the default (pypi) index, `[]` means use no indexes.
    indexes = None
    if options.indexes != [_PYPI] and options.indexes is not None:
        indexes = [str(index) for index in options.indexes]

    for requirements_pex in options.requirements_pexes:
        pex_builder.add_from_requirements_pex(requirements_pex)

    with TRACER.timed("Resolving distributions ({})".format(reqs + options.requirement_files)):
        network_configuration = NetworkConfiguration.create(
            cache_ttl=options.cache_ttl,
            retries=options.retries,
            timeout=options.timeout,
            headers=options.headers,
            proxy=options.proxy,
            cert=options.cert,
            client_cert=options.client_cert,
        )

        try:
            resolveds = resolve_multi(
                requirements=reqs,
                requirement_files=options.requirement_files,
                constraint_files=options.constraint_files,
                allow_prereleases=options.allow_prereleases,
                transitive=options.transitive,
                interpreters=interpreters,
                platforms=list(platforms),
                indexes=indexes,
                find_links=options.find_links,
                network_configuration=network_configuration,
                cache=cache,
                build=options.build,
                use_wheel=options.use_wheel,
                compile=options.compile,
                manylinux=options.manylinux,
                max_parallel_jobs=options.max_parallel_jobs,
                ignore_errors=options.ignore_errors,
            )

            for resolved_dist in resolveds:
                log(
                    "  %s -> %s" % (resolved_dist.requirement, resolved_dist.distribution),
                    V=options.verbosity,
                )
                pex_builder.add_distribution(resolved_dist.distribution)
                pex_builder.add_requirement(resolved_dist.requirement)
        except Unsatisfiable as e:
            die(e)

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
    # inherit-path used to be a boolean arg (so either was absent, or --inherit-path)
    # Now it takes a string argument, so --inherit-path is invalid.
    # Fix up the args we're about to parse to preserve backwards compatibility.
    if arg == "--inherit-path":
        return "--inherit-path=prefer"
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

    options, reqs = parser.parse_args(args=args)

    # Ensure the TMPDIR is an absolute path (So subprocesses that change CWD can find it) and
    # that it exists.
    tmpdir = os.path.realpath(options.tmpdir)
    if not os.path.exists(tmpdir):
        die("The specified --tmpdir does not exist: {}".format(tmpdir))
    if not os.path.isdir(tmpdir):
        die("The specified --tmpdir is not a directory: {}".format(tmpdir))
    tempfile.tempdir = os.environ["TMPDIR"] = tmpdir

    if options.cache_dir:
        pex_warnings.warn("The --cache-dir option is deprecated, use --pex-root instead.")
        if options.pex_root and options.cache_dir != options.pex_root:
            die(
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

    if options.python and options.interpreter_constraint:
        die('The "--python" and "--interpreter-constraint" options cannot be used together.')

    with ENV.patch(
        PEX_VERBOSE=str(options.verbosity), PEX_ROOT=pex_root, TMPDIR=tmpdir
    ) as patched_env:
        with TRACER.timed("Building pex"):
            pex_builder = build_pex(reqs, options, cache=ENV.PEX_ROOT)

        pex_builder.freeze(bytecode_compile=options.compile)
        interpreter = pex_builder.interpreter
        pex = PEX(
            pex_builder.path(), interpreter=interpreter, verify_entry_point=options.validate_ep
        )

        if options.pex_name is not None:
            log("Saving PEX file to %s" % options.pex_name, V=options.verbosity)
            tmp_name = options.pex_name + "~"
            safe_delete(tmp_name)
            pex_builder.build(
                tmp_name,
                bytecode_compile=options.compile,
                deterministic_timestamp=not options.use_system_time,
            )
            os.rename(tmp_name, options.pex_name)
        else:
            if not _compatible_with_current_platform(interpreter, options.platforms):
                log("WARNING: attempting to run PEX with incompatible platforms!", V=1)
                log(
                    "Running on platform {} but built for {}".format(
                        interpreter.platform, ", ".join(map(str, options.platforms))
                    ),
                    V=1,
                )

            log(
                "Running PEX file at %s with args %s" % (pex_builder.path(), cmdline),
                V=options.verbosity,
            )
            sys.exit(pex.run(args=list(cmdline), env=patched_env))


if __name__ == "__main__":
    main()
