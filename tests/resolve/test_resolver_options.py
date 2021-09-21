# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from argparse import ArgumentParser

import pytest

from pex.resolve import resolver_options
from pex.resolve.resolver_configuration import PexRepositoryConfiguration, PipConfiguration
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import List, Sequence, Union


def compute_resolver_configuration(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
):
    # type: (...) -> Union[PipConfiguration, PexRepositoryConfiguration]
    options = parser.parse_args(args=args)
    return resolver_options.configure(options)


def compute_pip_configuration(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
):
    # type: (...) -> PipConfiguration
    resolver_configuration = compute_resolver_configuration(parser, args)
    assert isinstance(resolver_configuration, PipConfiguration)
    return resolver_configuration


def compute_indexes(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
):
    # type: (...) -> Sequence[str]
    pip_configuration = compute_pip_configuration(parser, args)
    return pip_configuration.indexes


def test_clp_no_pypi_option(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    assert len(compute_indexes(parser, args=[])) == 1

    assert (
        len(compute_indexes(parser, args=["--no-pypi"])) == 0
    ), "--no-pypi should remove the pypi index."


def test_clp_pypi_option_duplicate(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    indexes = compute_indexes(parser, args=[])
    assert len(indexes) == 1

    indexes2 = compute_indexes(parser, args=["--pypi"])
    assert len(indexes2) == 1

    assert indexes == indexes2


def test_clp_find_links_option(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    pip_configuration = compute_pip_configuration(parser, args=["-f", "http://www.example.com"])
    assert len(pip_configuration.indexes) == 1
    assert len(pip_configuration.find_links) == 1


def test_clp_index_option(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    indexes = compute_indexes(parser, args=[])
    assert len(indexes) == 1

    indexes2 = compute_indexes(parser, args=["-i", "http://www.example.com"])
    assert len(indexes2) == 2

    assert indexes2[0] == indexes[0]
    assert indexes2[1] == "http://www.example.com"


def test_clp_index_option_render(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    indexes = compute_indexes(parser, args=["--index", "http://www.example.com"])
    assert ("https://pypi.org/simple", "http://www.example.com") == indexes


def test_clp_build_precedence(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    pip_configuration = compute_pip_configuration(parser, args=["--no-build"])
    assert not pip_configuration.allow_builds

    pip_configuration = compute_pip_configuration(parser, args=["--build"])
    assert pip_configuration.allow_builds

    pip_configuration = compute_pip_configuration(parser, args=["--no-wheel"])
    assert not pip_configuration.allow_wheels

    pip_configuration = compute_pip_configuration(parser, args=["--wheel"])
    assert pip_configuration.allow_wheels


def test_pex_repository(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser, include_pex_repository=True)

    resolver_configuration = compute_resolver_configuration(
        parser, args=["--pex-repository", "a.pex"]
    )
    assert isinstance(resolver_configuration, PexRepositoryConfiguration)
    assert "a.pex" == resolver_configuration.pex_repository


def test_invalid_configuration(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser, include_pex_repository=True)

    with pytest.raises(resolver_options.InvalidConfigurationError):
        compute_resolver_configuration(
            parser, args=["--pex-repository", "a.pex", "-f", "https://a.find/links/repo"]
        )
