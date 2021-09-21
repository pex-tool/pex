# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from argparse import ArgumentParser

import pytest

from pex.resolve import resolve_options
from pex.resolve.resolve_configuration import PexRepositoryConfiguration, PipConfiguration
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import List, Sequence, Union


def compute_resolver_configuration(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
):
    # type: (...) -> Union[PipConfiguration, PexRepositoryConfiguration]
    options = parser.parse_args(args=args)
    return resolve_options.configure(options)


def compute_pip_configuration(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
):
    # type: (...) -> PipConfiguration
    resolve_configuration = compute_resolver_configuration(parser, args)
    assert isinstance(resolve_configuration, PipConfiguration)
    return resolve_configuration


def compute_indexes(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
):
    # type: (...) -> Sequence[str]
    package_index_configuration = compute_pip_configuration(parser, args)
    return package_index_configuration.indexes


def test_clp_no_pypi_option(parser):
    # type: (ArgumentParser) -> None
    resolve_options.register(parser)

    assert len(compute_indexes(parser, args=[])) == 1

    assert (
        len(compute_indexes(parser, args=["--no-pypi"])) == 0
    ), "--no-pypi should remove the pypi index."


def test_clp_pypi_option_duplicate(parser):
    # type: (ArgumentParser) -> None
    resolve_options.register(parser)

    indexes = compute_indexes(parser, args=[])
    assert len(indexes) == 1

    indexes2 = compute_indexes(parser, args=["--pypi"])
    assert len(indexes2) == 1

    assert indexes == indexes2


def test_clp_find_links_option(parser):
    # type: (ArgumentParser) -> None
    resolve_options.register(parser)

    package_index_configuration = compute_pip_configuration(
        parser, args=["-f", "http://www.example.com"]
    )
    assert len(package_index_configuration.indexes) == 1
    assert len(package_index_configuration.find_links) == 1


def test_clp_index_option(parser):
    # type: (ArgumentParser) -> None
    resolve_options.register(parser)

    indexes = compute_indexes(parser, args=[])
    assert len(indexes) == 1

    indexes2 = compute_indexes(parser, args=["-i", "http://www.example.com"])
    assert len(indexes2) == 2

    assert indexes2[0] == indexes[0]
    assert indexes2[1] == "http://www.example.com"


def test_clp_index_option_render(parser):
    # type: (ArgumentParser) -> None
    resolve_options.register(parser)

    indexes = compute_indexes(parser, args=["--index", "http://www.example.com"])
    assert ("https://pypi.org/simple", "http://www.example.com") == indexes


def test_clp_build_precedence(parser):
    # type: (ArgumentParser) -> None
    resolve_options.register(parser)

    resolve_configuration = compute_pip_configuration(parser, args=["--no-build"])
    assert not resolve_configuration.allow_builds

    resolve_configuration = compute_pip_configuration(parser, args=["--build"])
    assert resolve_configuration.allow_builds

    resolve_configuration = compute_pip_configuration(parser, args=["--no-wheel"])
    assert not resolve_configuration.allow_wheels

    resolve_configuration = compute_pip_configuration(parser, args=["--wheel"])
    assert resolve_configuration.allow_wheels


def test_pex_repository(parser):
    # type: (ArgumentParser) -> None
    resolve_options.register(parser, include_pex_repository=True)

    resolver_configuration = compute_resolver_configuration(
        parser, args=["--pex-repository", "a.pex"]
    )
    assert isinstance(resolver_configuration, PexRepositoryConfiguration)
    assert "a.pex" == resolver_configuration.pex_repository


def test_invalid_configuration(parser):
    # type: (ArgumentParser) -> None
    resolve_options.register(parser, include_pex_repository=True)

    with pytest.raises(resolve_options.InvalidConfigurationError):
        compute_resolver_configuration(
            parser, args=["--pex-repository", "a.pex", "-f", "https://a.find/links/repo"]
        )
