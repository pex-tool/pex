# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from argparse import Action, ArgumentTypeError

from pex import pex_warnings
from pex.argparse import HandleBoolAction
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pip import ResolverVersion
from pex.resolve.resolve_configuration import (
    PYPI,
    PackageIndexConfiguration,
    PexRepository,
    ResolveConfiguration,
)
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace, _ArgumentGroup


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


def register(parser):
    # type: (ArgumentParser) -> _ArgumentGroup
    """Register resolve options with the given parse; returning the argument group that was used."""

    group = parser.add_argument_group(
        title="Resolver options",
        description=(
            "Tailor how to find, resolve and translate the packages that get put into the PEX "
            "environment."
        ),
    )

    default_package_index_configuration = PackageIndexConfiguration()
    group.add_argument(
        "--resolver-version",
        dest="resolver_version",
        default=default_package_index_configuration.resolver_version,
        choices=ResolverVersion.values(),
        type=ResolverVersion.for_value,
        help=(
            "The dependency resolver version to use. Read more at "
            "https://pip.pypa.io/en/stable/user_guide/#resolver-changes-2020"
        ),
    )
    group.add_argument(
        "--pypi",
        "--no-pypi",
        "--no-index",
        dest="pypi",
        action=HandleBoolAction,
        default=True,
        help="Whether to use PyPI to resolve dependencies.",
    )
    group.add_argument(
        "-f",
        "--find-links",
        "--repo",
        metavar="PATH/URL",
        action="append",
        dest="find_links",
        type=str,
        help="Additional repository path (directory or URL) to look for requirements.",
    )
    group.add_argument(
        "-i",
        "--index",
        "--index-url",
        metavar="URL",
        action="append",
        dest="indexes",
        type=str,
        help="Additional cheeseshop indices to use to satisfy requirements.",
    )

    default_net_config = NetworkConfiguration()
    group.add_argument(
        "--retries",
        default=default_net_config.retries,
        type=int,
        help="Maximum number of retries each connection should attempt.",
    )
    group.add_argument(
        "--timeout",
        metavar="SECS",
        default=default_net_config.timeout,
        type=int,
        help="Set the socket timeout in seconds.",
    )
    group.add_argument(
        "--proxy",
        type=str,
        default=default_net_config.proxy,
        help="Specify a proxy in the form [user:passwd@]proxy.server:port.",
    )
    group.add_argument(
        "--cert",
        metavar="PATH",
        type=str,
        default=default_net_config.cert,
        help="Path to alternate CA bundle.",
    )
    group.add_argument(
        "--client-cert",
        metavar="PATH",
        type=str,
        default=default_net_config.client_cert,
        help=(
            "Path to an SSL client certificate which should be a single file containing the "
            "private key and the certificate in PEM format."
        ),
    )
    group.add_argument(
        "--cache-ttl",
        metavar="DEPRECATED",
        default=None,
        type=int,
        help="Deprecated: No longer used.",
    )
    group.add_argument(
        "-H",
        "--header",
        dest="headers",
        metavar="DEPRECATED",
        default=None,
        type=str,
        action="append",
        help="Deprecated: No longer used.",
    )

    parser.add_argument(
        "--pex-repository",
        dest="pex_repository",
        metavar="FILE",
        default=None,
        type=PexRepository,
        help=(
            "Resolve requirements from the given PEX file instead of from --index servers or "
            "--find-links repos."
        ),
    )

    default_resolve_configuration = ResolveConfiguration()
    group.add_argument(
        "--pre",
        "--no-pre",
        dest="allow_prereleases",
        default=default_resolve_configuration.allow_prereleases,
        action=HandleBoolAction,
        help="Whether to include pre-release and development versions of requirements.",
    )
    group.add_argument(
        "--wheel",
        "--no-wheel",
        "--no-use-wheel",
        dest="allow_wheels",
        default=default_resolve_configuration.allow_wheels,
        action=HandleBoolAction,
        help="Whether to allow wheel distributions.",
    )
    group.add_argument(
        "--build",
        "--no-build",
        dest="allow_builds",
        default=default_resolve_configuration.allow_builds,
        action=HandleBoolAction,
        help="Whether to allow building of distributions from source.",
    )
    group.add_argument(
        "--manylinux",
        "--no-manylinux",
        "--no-use-manylinux",
        dest="assume_manylinux",
        type=str,
        default=default_resolve_configuration.assume_manylinux,
        action=_ManylinuxAction,
        help="Whether to allow resolution of manylinux wheels for linux target platforms.",
    )
    group.add_argument(
        "--transitive",
        "--no-transitive",
        "--intransitive",
        dest="transitive",
        default=default_resolve_configuration.transitive,
        action=_HandleTransitiveAction,
        help="Whether to transitively resolve requirements.",
    )
    group.add_argument(
        "-j",
        "--jobs",
        metavar="JOBS",
        dest="max_jobs",
        type=int,
        default=default_resolve_configuration.max_jobs,
        help=(
            "The maximum number of parallel jobs to use when resolving, building and "
            "installing distributions. You might want to increase the maximum number of "
            "parallel jobs to potentially improve the latency of the pex creation process at "
            "the expense of other processes on your system."
        ),
    )

    return group


class InvalidConfigurationError(Exception):
    """Indicates an invalid resolve configuration."""


def create_resolve_configuration(options):
    # type: (Namespace) -> ResolveConfiguration
    """Creates a resolve configuration from options registered by `register`.

    :raise: :class:`InvalidConfigurationError` if the resolve configuration is invalid.
    """

    if options.pex_repository and (options.indexes or options.find_links):
        raise InvalidConfigurationError(
            'The "--pex-repository" option cannot be used together with the "--resolver-version", '
            '"--index" or "--find-links" options.'
        )

    if options.pex_repository:
        repository = options.pex_repository
    else:
        if options.cache_ttl:
            pex_warnings.warn("The --cache-ttl option is deprecated and no longer has any effect.")
        if options.headers:
            pex_warnings.warn("The --header option is deprecated and no longer has any effect.")

        indexes = OrderedSet(
            ([PYPI] if options.pypi else []) + (options.indexes or [])
        )  # type: OrderedSet[str]
        find_links = OrderedSet(options.find_links or ())  # type: OrderedSet[str]
        repository = PackageIndexConfiguration(
            resolver_version=options.resolver_version,
            indexes=indexes,
            find_links=find_links,
        )

    network_configuration = NetworkConfiguration(
        retries=options.retries,
        timeout=options.timeout,
        proxy=options.proxy,
        cert=options.cert,
        client_cert=options.client_cert,
    )

    return ResolveConfiguration(
        repository=repository,
        network_configuration=network_configuration,
        allow_prereleases=options.allow_prereleases,
        allow_wheels=options.allow_wheels,
        allow_builds=options.allow_builds,
        assume_manylinux=options.assume_manylinux,
        transitive=options.transitive,
        max_jobs=options.max_jobs,
    )
