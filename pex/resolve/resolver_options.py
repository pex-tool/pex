# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from argparse import Action, ArgumentTypeError, Namespace, _ActionsContainer

from pex import pex_warnings
from pex.argparse import HandleBoolAction
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.resolve.resolver_configuration import (
    PYPI,
    LockRepositoryConfiguration,
    PexRepositoryConfiguration,
    PipConfiguration,
    ReposConfiguration,
    ResolverVersion,
)
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Union


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
):
    # type: (...) -> None
    """Register resolver configuration options with the given parser.

    :param parser: The parser to register resolver configuration options with.
    :param include_pex_repository: Whether to include the `--pex-repository` option.
    :param include_lock: Whether to include the `--lock` option.
    """

    default_resolver_configuration = PipConfiguration()
    parser.add_argument(
        "--resolver-version",
        dest="resolver_version",
        default=default_resolver_configuration.resolver_version,
        choices=ResolverVersion.values(),
        type=ResolverVersion.for_value,
        help=(
            "The dependency resolver version to use. Read more at "
            "https://pip.pypa.io/en/stable/user_guide/#resolver-changes-2020"
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

    repository_choice = (
        parser.add_mutually_exclusive_group() if include_pex_repository and include_lock else parser
    )
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
        default=default_resolver_configuration.allow_wheels,
        action=HandleBoolAction,
        help="Whether to allow binary distributions.",
    )
    parser.add_argument(
        "--build",
        "--no-build",
        dest="allow_builds",
        default=default_resolver_configuration.allow_builds,
        action=HandleBoolAction,
        help="Whether to allow building of distributions from source.",
    )
    parser.add_argument(
        "--prefer-wheel",
        "--prefer-binary",
        "--no-prefer-wheel",
        "--no-prefer-binary",
        dest="prefer_older_binary",
        default=default_resolver_configuration.prefer_older_binary,
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
        default=default_resolver_configuration.use_pep517,
        action=HandleBoolAction,
        help=(
            "Whether to force use of PEP 517 for building source distributions into wheels ("
            "https://www.python.org/dev/peps/pep-0518) or force direct invocation of"
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
        default=default_resolver_configuration.build_isolation,
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
        LockRepositoryConfiguration, PexRepositoryConfiguration, PipConfiguration
    ]


def configure(options):
    # type: (Namespace) -> ResolverConfiguration
    """Creates a resolver configuration from options registered by `register`.

    :param options: The resolver configuration options.
    :raise: :class:`InvalidConfigurationError` if the resolver configuration is invalid.
    """

    pex_repository = getattr(options, "pex_repository", None)
    lock = getattr(options, "lock", None)
    if pex_repository and (options.indexes or options.find_links):
        raise InvalidConfigurationError(
            'The "--pex-repository" option cannot be used together with the "--index" or '
            '"--find-links" options.'
        )
    if lock and (options.indexes or options.find_links):
        raise InvalidConfigurationError(
            'The "--lock" option cannot be used together with the "--index" or '
            '"--find-links" options.'
        )

    if pex_repository:
        return PexRepositoryConfiguration(
            pex_repository=pex_repository,
            network_configuration=create_network_configuration(options),
            transitive=options.transitive,
        )
    pip_configuration = create_pip_configuration(options)
    if lock:
        return LockRepositoryConfiguration(
            lock_file=options.lock,
            pip_configuration=pip_configuration,
        )
    return pip_configuration


def create_pip_configuration(options):
    # type: (Namespace) -> PipConfiguration
    """Creates a Pip configuration from options registered by `register`.

    :param options: The Pip resolver configuration options.
    """

    if options.cache_ttl:
        pex_warnings.warn("The --cache-ttl option is deprecated and no longer has any effect.")
    if options.headers:
        pex_warnings.warn("The --header option is deprecated and no longer has any effect.")

    repos_configuration = create_repos_configuration(options)
    return PipConfiguration(
        resolver_version=options.resolver_version,
        repos_configuration=repos_configuration,
        network_configuration=create_network_configuration(options),
        allow_prereleases=options.allow_prereleases,
        allow_wheels=options.allow_wheels,
        allow_builds=options.allow_builds,
        prefer_older_binary=options.prefer_older_binary,
        use_pep517=options.use_pep517,
        build_isolation=options.build_isolation,
        transitive=options.transitive,
        max_jobs=get_max_jobs_value(options),
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
    return ReposConfiguration(indexes=tuple(indexes), find_links=tuple(find_links))


def create_network_configuration(options):
    # type: (Namespace) -> NetworkConfiguration
    """Creates a network configuration from options registered by `register_network_options`.

    :param options: The Pip resolver configuration options.
    """
    return NetworkConfiguration(
        retries=options.retries,
        timeout=options.timeout,
        proxy=options.proxy,
        cert=options.cert,
        client_cert=options.client_cert,
    )


def get_max_jobs_value(options):
    # type: (Namespace) -> int
    """Retrieves the max jobs value from the option registered by `register_max_jobs_option`.

    :param options: The max jobs configuration option.
    """
    return cast(int, options.max_jobs)
