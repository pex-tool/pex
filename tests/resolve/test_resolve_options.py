# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from argparse import ArgumentParser, ArgumentTypeError

import pytest

from pex.resolve import resolve_options
from pex.resolve.resolve_configuration import PackageIndexConfiguration, ResolveConfiguration
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import List, Sequence


@pytest.fixture
def parser():
    # type: () -> ArgumentParser
    return ArgumentParser()


def compute_resolve_configuration(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
):
    # type: (...) -> ResolveConfiguration
    options = parser.parse_args(args=args)
    return resolve_options.create_resolve_configuration(options)


def compute_package_index_configuration(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
):
    # type: (...) -> PackageIndexConfiguration
    resolve_configuration = compute_resolve_configuration(parser, args)
    repository = resolve_configuration.repository
    assert isinstance(repository, PackageIndexConfiguration)
    return repository


def compute_indexes(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
):
    # type: (...) -> Sequence[str]
    package_index_configuration = compute_package_index_configuration(parser, args)
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

    package_index_configuration = compute_package_index_configuration(
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

    resolve_configuration = compute_resolve_configuration(parser, args=["--no-build"])
    assert not resolve_configuration.allow_builds

    resolve_configuration = compute_resolve_configuration(parser, args=["--build"])
    assert resolve_configuration.allow_builds

    resolve_configuration = compute_resolve_configuration(parser, args=["--no-wheel"])
    assert not resolve_configuration.allow_wheels

    resolve_configuration = compute_resolve_configuration(parser, args=["--wheel"])
    assert resolve_configuration.allow_wheels


def test_clp_manylinux(parser):
    # type: (ArgumentParser) -> None
    resolve_options.register(parser)

    resolve_configuration = compute_resolve_configuration(parser, args=[])
    assert (
        resolve_configuration.assume_manylinux
    ), "The --manylinux option should default to some value."

    def assert_manylinux(value):
        # type: (str) -> None
        rc = compute_resolve_configuration(parser, args=["--manylinux", value])
        assert value == rc.assume_manylinux

    # Legacy manylinux standards should be supported.
    assert_manylinux("manylinux1_x86_64")
    assert_manylinux("manylinux2010_x86_64")
    assert_manylinux("manylinux2014_x86_64")

    # The modern open-ended glibc version based manylinux standards should be supported.
    assert_manylinux("manylinux_2_5_x86_64")
    assert_manylinux("manylinux_2_33_x86_64")

    resolve_configuration = compute_resolve_configuration(parser, args=["--no-manylinux"])
    assert resolve_configuration.assume_manylinux is None

    with pytest.raises(ArgumentTypeError):
        compute_resolve_configuration(parser, args=["--manylinux", "foo"])
