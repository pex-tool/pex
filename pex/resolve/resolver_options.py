# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import os
import tempfile
from argparse import Action, ArgumentError, ArgumentTypeError, Namespace, _ActionsContainer

from pex import pex_warnings
from pex.argparse import HandleBoolAction
from pex.dist_metadata import Requirement, is_sdist, is_wheel
from pex.fetcher import initialize_ssl_context
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.path_mappings import PathMapping, PathMappings
from pex.resolve.resolver_configuration import (
    PYPI,
    BuildConfiguration,
    LockRepositoryConfiguration,
    PexRepositoryConfiguration,
    PipConfiguration,
    PipLog,
    PreResolvedConfiguration,
    ReposConfiguration,
    ResolverVersion,
)
from pex.result import Error
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import List, Optional, Union


class _ManylinuxAction(Action):
    def __init__(self, *args, **kwargs):
        kwargs["nargs"] = "?"
        super(_ManylinuxAction, self).__init__(*args, **kwargs)

    def __call__(self, parser, namespace, value, option_str=None):
        if option_str.startswith("--no"):
            setattr(namespace, self.dest, None)
        elif value.startswith("manylinux"):
            setattr(namespace, self.dest, value)
        else:
            raise ArgumentTypeError(
                "Please specify a manylinux standard; ie: --manylinux=manylinux1. "
                "Given {}".format(value)
            )


class _HandleTransitiveAction(Action):
    def __init__(self, *args, **kwargs):
        kwargs["nargs"] = 0
        super(_HandleTransitiveAction, self).__init__(*args, **kwargs)

    def __call__(self, parser, namespace, value, option_str=None):
        setattr(namespace, self.dest, option_str == "--transitive")


def register(
    parser,  # type: _ActionsContainer
    include_pex_repository=False,  # type: bool
    include_lock=False,  # type: bool
    include_pre_resolved=False,  # type: bool
):
    # type: (...) -> None
    """Register resolver configuration options with the given parser.

    :param parser: The parser to register resolver configuration options with.
    :param include_pex_repository: Whether to include the `--pex-repository` option.
    :param include_lock: Whether to include the `--lock` option.
    :param include_pre_resolved: Whether to include the `--pre-resolved-dist` and
                                 `--pre-resolved-dists` options.
    """

    default_resolver_configuration = PipConfiguration()
    parser.add_argument(
        "--resolver-version",
        dest="resolver_version",
        default=None,
        choices=ResolverVersion.values(),
        type=ResolverVersion.for_value,
        help=(
            "The dependency resolver version to use. For any `--pip-version` older than 23.2 this "
            "defaults to {pip_legacy}. For `--pip-version` 23.2 and newer this defaults to "
            "{pip_2020} which is the only valid version. Read more at "
            "https://pip.pypa.io/en/stable/user_guide/#resolver-changes-2020".format(
                pip_legacy=ResolverVersion.PIP_LEGACY, pip_2020=ResolverVersion.PIP_2020
            )
        ),
    )
    parser.add_argument(
        "--pip-version",
        dest="pip_version",
        default=str(PipVersion.DEFAULT),
        choices=["latest", "vendored"] + [str(value) for value in PipVersion.values()],
        help=(
            "The version of Pip to use for resolving dependencies. The `latest` version refers to "
            "the latest version in this list ({latest}) which is not necessarily the latest Pip "
            "version released on PyPI.".format(latest=PipVersion.LATEST)
        ),
    )
    parser.add_argument(
        "--allow-pip-version-fallback",
        "--no-allow-pip-version-fallback",
        dest="allow_pip_version_fallback",
        default=default_resolver_configuration.allow_version_fallback,
        action=HandleBoolAction,
        help=(
            "Whether to allow --pip-version to be ignored if the requested version is not "
            "compatible with all of the selected interpreters. If fallback is allowed, a warning "
            "will be emitted when fallback is necessary. If fallback is not allowed, Pex will fail "
            "fast indicating the problematic selected interpreters."
        ),
    )
    parser.add_argument(
        "--extra-pip-requirement",
        dest="extra_pip_requirements",
        type=Requirement.parse,
        default=list(default_resolver_configuration.extra_requirements),
        action="append",
        help=(
            "Add this extra requirement to the Pip PEX uses by Pex to resolve distributions. "
            "Notably, this can be used to install keyring and keyring plugins for Pip to use. "
            "There is obviously a bootstrap issue here if your only available index is secured; "
            "so you may need to use an additional --find-links repo or --index that is not "
            "secured in order to bootstrap keyring. "
            "See: https://pip.pypa.io/en/stable/topics/authentication/#keyring-support"
        ),
    )

    register_use_pip_config(parser)

    parser.add_argument(
        "--keyring-provider",
        metavar="PROVIDER",
        dest="keyring_provider",
        type=str,
        default=None,
        help=(
            "Configure Pip to use the given keyring provider to obtain authentication for package indexes. "
            "Please note that keyring support is only available in Pip v23.1 and later versions. "
            "There is obviously a bootstrap issue here if your only available index is secured; "
            "so you may need to use an additional --find-links repo or --index that is not "
            "secured in order to bootstrap a version of Pip which supports keyring. "
            "See: https://pip.pypa.io/en/stable/topics/authentication/#keyring-support"
        ),
    )

    register_repos_options(parser)
    register_network_options(parser)

    parser.add_argument(
        "--cache-ttl",
        metavar="DEPRECATED",
        default=None,
        type=int,
        help="Deprecated: No longer used.",
    )
    parser.add_argument(
        "-H",
        "--header",
        dest="headers",
        metavar="DEPRECATED",
        default=None,
        type=str,
        action="append",
        help="Deprecated: No longer used.",
    )

    repository_types = 0
    if include_pex_repository:
        repository_types += 1
    if include_lock:
        repository_types += 1
    if include_pre_resolved:
        repository_types += 1

    repository_choice = parser.add_mutually_exclusive_group() if repository_types > 1 else parser
    if include_pex_repository:
        repository_choice.add_argument(
            "--pex-repository",
            dest="pex_repository",
            metavar="FILE",
            default=None,
            type=str,
            help=(
                "Resolve requirements from the given PEX file instead of from --index servers, "
                "--find-links repos or a --lock file."
            ),
        )
    if include_lock:
        repository_choice.add_argument(
            "--lock",
            dest="lock",
            metavar="FILE",
            default=None,
            type=str,
            help=(
                "Resolve requirements from the given lock file created by Pex instead of from "
                "--index servers, --find-links repos or a --pex-repository. If no requirements are "
                "specified, will install the entire lock."
            ),
        )
        register_lock_options(parser)
    if include_pre_resolved:
        repository_choice.add_argument(
            "--pre-resolved-dist",
            "--pre-resolved-dists",
            dest="pre_resolved_dists",
            metavar="FILE",
            default=[],
            type=str,
            action="append",
            help=(
                "If a wheel, add it to the PEX. If an sdist, build wheels for the selected targets "
                "and add them to the PEX. Otherwise, if a directory, add all the distributions "
                "found in the given directory to the PEX, building wheels from any sdists first. "
                "This option can be used to add a pre-resolved dependency set to a PEX. By "
                "default, Pex will ensure the dependencies added form a closure."
            ),
        )

    parser.add_argument(
        "--pre",
        "--no-pre",
        dest="allow_prereleases",
        default=default_resolver_configuration.allow_prereleases,
        action=HandleBoolAction,
        help="Whether to include pre-release and development versions of requirements.",
    )
    parser.add_argument(
        "--wheel",
        "--binary",
        "--no-wheel",
        "--no-use-wheel",
        "--no-binary",
        "--no-use-binary",
        dest="allow_wheels",
        default=default_resolver_configuration.build_configuration.allow_wheels,
        action=HandleBoolAction,
        help="Whether to allow binary distributions.",
    )

    def valid_project_name(arg):
        # type: (str) -> ProjectName
        try:
            return ProjectName(arg, validated=True)
        except ProjectName.InvalidError as e:
            raise ArgumentTypeError(str(e))

    parser.add_argument(
        "--only-binary",
        "--only-wheel",
        dest="only_wheels",
        default=[],
        action="append",
        help="Names of projects to only ever accept pre-built wheels for.",
        type=valid_project_name,
    )
    parser.add_argument(
        "--build",
        "--no-build",
        dest="allow_builds",
        default=default_resolver_configuration.build_configuration.allow_builds,
        action=HandleBoolAction,
        help="Whether to allow building of distributions from source.",
    )
    parser.add_argument(
        "--only-build",
        dest="only_builds",
        default=[],
        action="append",
        help="Names of projects to only ever build from source.",
        type=valid_project_name,
    )
    parser.add_argument(
        "--prefer-wheel",
        "--prefer-binary",
        "--no-prefer-wheel",
        "--no-prefer-binary",
        dest="prefer_older_binary",
        default=default_resolver_configuration.build_configuration.prefer_older_binary,
        action=HandleBoolAction,
        help=(
            "Whether to prefer older binary distributions to newer source distributions (prefer "
            "not building wheels)."
        ),
    )
    parser.add_argument(
        "--force-pep517",
        "--use-pep517",
        "--no-use-pep517",
        dest="use_pep517",
        default=default_resolver_configuration.build_configuration.use_pep517,
        action=HandleBoolAction,
        help=(
            "Whether to force use of PEP 517 for building source distributions into wheels ("
            "https://www.python.org/dev/peps/pep-0517) or force direct invocation of"
            "`setup.py bdist_wheel` (which requires all source distributions have a `setup.py` "
            "based build). Defaults to using PEP-517 only when a `pyproject.toml` file is present "
            "with a `build-system` section. If PEP-517 is forced (--use-pep517 is passed) and no "
            "`pyproject.toml` file is present or one is but does not have a `build-system` section "
            "defined, then the build is executed as if a `pyproject.toml` was present with a "
            '`build-system` section comprised of `requires = ["setuptools>=40.8.0", "wheel"]` and '
            '`build-backend = "setuptools.build_meta:__legacy__"`.'
        ),
    )
    parser.add_argument(
        "--build-isolation",
        "--no-build-isolation",
        dest="build_isolation",
        default=default_resolver_configuration.build_configuration.build_isolation,
        action=HandleBoolAction,
        help=(
            "Disable `sys.path` isolation when building a modern source distribution. Build "
            "dependencies specified by PEP 518 (https://www.python.org/dev/peps/pep-0518) must "
            "already be installed on the `sys.path` if this option is used."
        ),
    )
    parser.add_argument(
        "--transitive",
        "--no-transitive",
        "--intransitive",
        dest="transitive",
        default=default_resolver_configuration.transitive,
        action=_HandleTransitiveAction,
        help="Whether to transitively resolve requirements.",
    )
    register_max_jobs_option(parser)
    register_pip_log(parser)


class HandlePipDownloadLogAction(Action):
    def __init__(self, *args, **kwargs):
        kwargs["nargs"] = "?"
        super(HandlePipDownloadLogAction, self).__init__(*args, **kwargs)

    def __call__(self, parser, namespace, value, option_str=None):
        pip_log = None  # type: Optional[PipLog]
        if option_str.startswith("--no"):
            if value:
                raise ArgumentError(
                    self,
                    "Cannot specify a Pip log path and turn off Pip log preservation at the same "
                    "time. Given: `{option_str} {value}`".format(
                        option_str=option_str, value=value
                    ),
                )
        elif not value:
            pip_log = PipLog(
                path=os.path.join(tempfile.mkdtemp(prefix="pex-pip-log."), "pip.log"),
                user_specified=False,
            )
        else:
            path = os.path.realpath(value)
            if os.path.exists(path):
                if not os.path.isfile(path):
                    raise ArgumentError(
                        self,
                        "The requested `--pip-log` of {path} is a directory.\n"
                        "The `--pip-log` argument must be either an existing file path, in which "
                        "case the file will be truncated to receive a fresh log, or else a "
                        "non-existent path, in which case it will be created. Note that using the "
                        "same `--pip-log` path in concurrent Pex executions is not "
                        "supported.".format(path=path),
                    )
                # N.B.: This truncates the file in a way compatible with Python 2.7 (os.truncate
                # was introduced in 3.3).
                open(path, "w").close()
            pip_log = PipLog(path=value, user_specified=True)
        setattr(namespace, self.dest, pip_log)


def register_pip_log(parser):
    # type: (_ActionsContainer) -> None
    parser.add_argument(
        "--pip-log",
        "--preserve-pip-download-log",
        "--no-preserve-pip-download-log",
        dest="pip_log",
        default=PipConfiguration().log,
        action=HandlePipDownloadLogAction,
        help=(
            "With no argument, preserve the `pip download` log and print its location to stderr. "
            "With a log path argument, truncate the log if it exists and create it if it does not "
            "already exist, and send Pip log output there."
        ),
    )


def get_pip_log(options):
    # type: (Namespace) -> Optional[PipLog]
    return cast("Optional[PipLog]", options.pip_log)


def register_use_pip_config(parser):
    # type: (_ActionsContainer) -> None
    """Register an option to control Pip config hermeticity.

    :param parser: The parser to register the Pip config hermeticity option with.
    """
    parser.add_argument(
        "--use-pip-config",
        "--no-use-pip-config",
        dest="use_pip_config",
        default=None,
        action=HandleBoolAction,
        help=(
            "Whether to allow Pip to read its local configuration files and PIP_ env vars from "
            "the environment."
        ),
    )


def get_use_pip_config_value(options):
    # type: (Namespace) -> bool
    """Retrieves the use Pip config value from the option registered by `register_use_pip_config`.

    :param options: Parsed options containing use Pip config configuration option.
    """
    if options.use_pip_config is not None:
        return cast(bool, options.use_pip_config)
    # An affordance for tests to point at the devpi server.
    # TODO(John Sirois): https://github.com/pex-tool/pex/issues/2242
    #  Improve options system to accept command line args or env vars in general which will promote
    #  PEX_USE_PIP_CONFIG (no leading underscore) to a 1st class Pex CLI control knob.
    return os.environ.get("_PEX_USE_PIP_CONFIG", "False").lower() in ("1", "true")


def register_lock_options(parser):
    # type: (_ActionsContainer) -> None
    """Register lock options with the given parser.

    :param parser: The parser to register lock configuration options with.
    """
    parser.add_argument(
        "--path-mapping",
        dest="path_mappings",
        action="append",
        default=[],
        type=str,
        help=(
            "A mapping of the form `NAME|PATH|DESCRIPTION` of a logical name to a concrete local "
            "absolute path with an optional description. Can be specified multiple times. The "
            "mapping must include the pipe (`|`) separated name and absolute path components, but "
            "the trailing pipe-separated description is optional. The mapping is used when "
            "creating, and later reading, lock files to ensure the lock file created on one "
            "machine can be used on another with a potentially different realization of various "
            "paths used in the resolve. A typical example is a find-links repo. This might be "
            "provided on the file-system via a network mount instead of via an HTTP(S) server and "
            "that network mount may be at different absolute paths on different machines. "
            "Classically, it may be in a user's home directory; whose path will vary from user to "
            "user."
        ),
    )


def register_repos_options(parser):
    # type: (_ActionsContainer) -> None
    """Register repos configuration options with the given parser.

    :param parser: The parser to register repos configuration options with.
    """
    parser.add_argument(
        "--pypi",
        "--no-pypi",
        "--no-index",
        dest="pypi",
        action=HandleBoolAction,
        default=True,
        help="Whether to use PyPI to resolve dependencies.",
    )
    parser.add_argument(
        "-f",
        "--find-links",
        "--repo",
        metavar="PATH/URL",
        action="append",
        dest="find_links",
        type=str,
        help="Additional repository path (directory or URL) to look for requirements.",
    )
    parser.add_argument(
        "-i",
        "--index",
        "--index-url",
        metavar="URL",
        action="append",
        dest="indexes",
        type=str,
        help="Additional cheeseshop indices to use to satisfy requirements.",
    )


def register_network_options(parser):
    # type: (_ActionsContainer) -> None
    """Register network configuration options with the given parser.

    :param parser: The parser to register network configuration options with.
    """
    default_resolver_configuration = PipConfiguration()
    default_network_configuration = default_resolver_configuration.network_configuration
    parser.add_argument(
        "--retries",
        default=default_network_configuration.retries,
        type=int,
        help="Maximum number of retries each connection should attempt.",
    )
    parser.add_argument(
        "--timeout",
        metavar="SECS",
        default=default_network_configuration.timeout,
        type=int,
        help="Set the socket timeout in seconds.",
    )
    parser.add_argument(
        "--proxy",
        type=str,
        default=default_network_configuration.proxy,
        help="Specify a proxy in the form http(s)://[user:passwd@]proxy.server:port.",
    )
    parser.add_argument(
        "--cert",
        metavar="PATH",
        type=str,
        default=default_network_configuration.cert,
        help="Path to alternate CA bundle.",
    )
    parser.add_argument(
        "--client-cert",
        metavar="PATH",
        type=str,
        default=default_network_configuration.client_cert,
        help=(
            "Path to an SSL client certificate which should be a single file containing the "
            "private key and the certificate in PEM format."
        ),
    )


def register_max_jobs_option(parser):
    # type: (_ActionsContainer) -> None
    """Register the max jobs configuration option with the given parser.

    :param parser: The parser to register the max job option with.
    """
    default_resolver_configuration = PipConfiguration()
    parser.add_argument(
        "-j",
        "--jobs",
        metavar="JOBS",
        dest="max_jobs",
        type=int,
        default=default_resolver_configuration.max_jobs,
        help=(
            "The maximum number of parallel jobs to use when resolving, building and "
            "installing distributions. You might want to increase the maximum number of "
            "parallel jobs to potentially improve the latency of the pex creation process at "
            "the expense of other processes on your system."
        ),
    )


class InvalidConfigurationError(Exception):
    """Indicates an invalid resolver configuration."""


if TYPE_CHECKING:
    ResolverConfiguration = Union[
        LockRepositoryConfiguration,
        PexRepositoryConfiguration,
        PipConfiguration,
        PreResolvedConfiguration,
    ]


def configure(
    options,  # type: Namespace
    use_system_time=False,  # type: bool
):
    # type: (...) -> ResolverConfiguration
    """Creates a resolver configuration from options registered by `register`.

    :param options: The resolver configuration options.
    :param use_system_time: `False` to attempt use a reproducible timestamp for builds.
    :raise: :class:`InvalidConfigurationError` if the resolver configuration is invalid.
    """

    pip_configuration = create_pip_configuration(options, use_system_time=use_system_time)

    pex_repository = getattr(options, "pex_repository", None)
    if pex_repository:
        if options.indexes or options.find_links:
            raise InvalidConfigurationError(
                'The "--pex-repository" option cannot be used together with the "--index" or '
                '"--find-links" options.'
            )
        return PexRepositoryConfiguration(
            pex_repository=pex_repository, pip_configuration=pip_configuration
        )

    lock = getattr(options, "lock", None)
    if lock:
        return LockRepositoryConfiguration(
            parse_lock=lambda: parse_lockfile(options, lock_file_path=lock),
            lock_file_path=lock,
            pip_configuration=pip_configuration,
        )

    pre_resolved_dists = getattr(options, "pre_resolved_dists", None)
    if pre_resolved_dists:
        sdists = []  # type: List[str]
        wheels = []  # type: List[str]
        for dist_or_dir in pre_resolved_dists:
            abs_dist_or_dir = os.path.expanduser(dist_or_dir)
            dists = (
                [abs_dist_or_dir]
                if os.path.isfile(abs_dist_or_dir)
                else glob.glob(os.path.join(abs_dist_or_dir, "*"))
            )
            for dist in dists:
                if not os.path.isfile(dist):
                    continue
                if is_wheel(dist):
                    wheels.append(dist)
                elif is_sdist(dist):
                    sdists.append(dist)
        return PreResolvedConfiguration(
            sdists=tuple(sdists), wheels=tuple(wheels), pip_configuration=pip_configuration
        )

    return pip_configuration


def create_pip_configuration(
    options,  # type: Namespace
    use_system_time=False,  # type: bool
):
    # type: (...) -> PipConfiguration
    """Creates a Pip configuration from options registered by `register`.

    :param options: The Pip resolver configuration options.
    :param use_system_time: `False` to attempt use a reproducible timestamp for builds.
    """

    if options.cache_ttl:
        pex_warnings.warn("The --cache-ttl option is deprecated and no longer has any effect.")
    if options.headers:
        pex_warnings.warn("The --header option is deprecated and no longer has any effect.")

    repos_configuration = create_repos_configuration(options)

    pip_version = None  # type: Optional[PipVersionValue]
    if options.pip_version == "latest":
        pip_version = PipVersion.LATEST
    elif options.pip_version == "vendored":
        pip_version = PipVersion.VENDORED
    elif options.pip_version:
        pip_version = PipVersion.for_value(options.pip_version)

    resolver_version = options.resolver_version or ResolverVersion.default(pip_version=pip_version)
    if not ResolverVersion.applies(resolver_version, pip_version=pip_version):
        raise InvalidConfigurationError(
            "Pip {pip_version} does not support {resolver_version}.".format(
                pip_version=pip_version, resolver_version=resolver_version
            )
        )

    build_configuration = BuildConfiguration.create(
        allow_wheels=options.allow_wheels,
        only_wheels=options.only_wheels,
        allow_builds=options.allow_builds,
        only_builds=options.only_builds,
        prefer_older_binary=options.prefer_older_binary,
        use_pep517=options.use_pep517,
        build_isolation=options.build_isolation,
        use_system_time=use_system_time,
    )

    return PipConfiguration(
        repos_configuration=repos_configuration,
        network_configuration=create_network_configuration(options),
        allow_prereleases=options.allow_prereleases,
        build_configuration=build_configuration,
        transitive=options.transitive,
        max_jobs=get_max_jobs_value(options),
        log=get_pip_log(options),
        version=pip_version,
        resolver_version=resolver_version,
        allow_version_fallback=options.allow_pip_version_fallback,
        use_pip_config=get_use_pip_config_value(options),
        extra_requirements=tuple(options.extra_pip_requirements),
        keyring_provider=options.keyring_provider,
    )


def create_repos_configuration(options):
    # type: (Namespace) -> ReposConfiguration
    """Creates a repos configuration from options registered by `register_repos_options`.

    :param options: The Pip resolver configuration options.
    """
    indexes = OrderedSet(
        ([PYPI] if options.pypi else []) + (options.indexes or [])
    )  # type: OrderedSet[str]
    find_links = OrderedSet(options.find_links or ())  # type: OrderedSet[str]
    return ReposConfiguration.create(indexes=tuple(indexes), find_links=tuple(find_links))


def create_network_configuration(options):
    # type: (Namespace) -> NetworkConfiguration
    """Creates a network configuration from options registered by `register_network_options`.

    :param options: The Pip resolver configuration options.
    """
    network_configuration = NetworkConfiguration(
        retries=options.retries,
        timeout=options.timeout,
        proxy=options.proxy,
        cert=options.cert,
        client_cert=options.client_cert,
    )
    initialize_ssl_context(network_configuration=network_configuration)
    return network_configuration


def get_max_jobs_value(options):
    # type: (Namespace) -> int
    """Retrieves the max jobs value from the option registered by `register_max_jobs_option`.

    :param options: The max jobs configuration option.
    """
    return cast(int, options.max_jobs)


def _parse_path_mapping(path_mapping):
    # type: (str) -> PathMapping
    components = path_mapping.split("|", 2)
    if len(components) < 2:
        raise ArgumentTypeError(
            "A path mapping must be of the form `NAME|PATH` with an optional trailing "
            "`|DESCRIPTION`, given: {path_mapping}.\n"
            "For example: `FL|/path/to/local/find-links/repo/directory` indicates that find-links "
            "requirements or URLs starting with `/path/to/local/find-links/repo/directory` should "
            "have that absolute root path replaced with the `${{FL}}` placeholder name.\n"
            "Alternatively, you could use the form with a trailing description to make it more "
            "clear what value should be substituted for `${{FL}}` when the mapping is later read, "
            "e.g.: `FL|/local/path|The local find-links repo path`."
            "".format(path_mapping=path_mapping)
        )
    name, path = components[:2]
    description = components[2] if len(components) == 3 else None
    return PathMapping(path=path, name=name, description=description)


def get_path_mappings(options):
    # type: (Namespace) -> PathMappings
    """Retrieves the PathMappings value from the options registered by `register_lock_options`.

    :param options: The lock configuration options.
    """
    return PathMappings(
        mappings=tuple(_parse_path_mapping(path_mapping) for path_mapping in options.path_mappings)
    )


def parse_lockfile(
    options,  # type: Namespace
    lock_file_path=None,  # type: Optional[str]
):
    # type: (...) -> Union[Lockfile, Error]
    path = lock_file_path or options.lock
    path_mappings = get_path_mappings(options)
    with TRACER.timed("Parsing lock {lockfile}".format(lockfile=path)):
        try:
            return json_codec.load(path, path_mappings=path_mappings)
        except json_codec.PathMappingError as e:
            return Error(
                "The lockfile at {path} requires specifying {prefix}"
                "'--path-mapping' {values} for: {required_paths}\n"
                "Given {given_mappings_verbiage}\n"
                "{maybe_path_mappings}"
                "Which left the following path mappings unspecified:\n"
                "{unspecified_paths}\n"
                "\n"
                "To fix, add command line options for:\n{examples}".format(
                    path=path,
                    prefix="" if len(e.required_path_mappings) > 1 else "a ",
                    values="values" if len(e.required_path_mappings) > 1 else "value",
                    required_paths=", ".join(sorted(e.required_path_mappings)),
                    given_mappings_verbiage="the following path mappings:"
                    if path_mappings.mappings
                    else "no path mappings.",
                    maybe_path_mappings="{path_mappings}\n".format(
                        path_mappings="\n".join(
                            sorted(
                                "--path-mapping '{mapping}'".format(
                                    mapping="|".join((mapping.name, mapping.path))
                                )
                                for mapping in path_mappings.mappings
                            )
                        )
                    )
                    if path_mappings.mappings
                    else "",
                    unspecified_paths="\n".join(
                        sorted(
                            (
                                "{path}: {description}".format(path=path, description=description)
                                if description
                                else path
                            )
                            for path, description in e.required_path_mappings.items()
                            if path in e.unspecified_paths
                        )
                    ),
                    examples="\n".join(
                        sorted(
                            "--path-mapping '{path}|<path of {path}>'".format(path=path)
                            for path in e.required_path_mappings
                            if path in e.unspecified_paths
                        )
                    ),
                )
            )
