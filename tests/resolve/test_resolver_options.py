# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import re
from argparse import ArgumentParser

import pytest

from pex.common import touch
from pex.pex_warnings import PEXWarning
from pex.pip.version import PipVersion
from pex.resolve import resolver_configuration, resolver_options
from pex.resolve.resolver_configuration import (
    BuildConfiguration,
    PexRepositoryConfiguration,
    PipConfiguration,
    PreResolvedConfiguration,
    ReposConfiguration,
)
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, List

    from pex.resolve.resolver_options import ResolverConfiguration


def compute_resolver_configuration(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
):
    # type: (...) -> ResolverConfiguration
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


def compute_build_configuration(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
):
    # type: (...) -> BuildConfiguration
    return compute_pip_configuration(parser, args).build_configuration


def compute_repos_configuration(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
):
    # type: (...) -> ReposConfiguration
    pip_configuration = compute_pip_configuration(parser, args)
    return pip_configuration.repos_configuration


def test_clp_no_pypi_option(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    repos_configuration = compute_repos_configuration(parser, args=[])
    assert len(repos_configuration.indexes) == 1
    assert len(repos_configuration.find_links) == 0

    repos_configuration = compute_repos_configuration(parser, args=["--no-pypi"])
    assert len(repos_configuration.indexes) == 0, "--no-pypi should remove the pypi index."
    assert len(repos_configuration.find_links) == 0


def test_clp_pypi_option_duplicate(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    repos_configuration = compute_repos_configuration(parser, args=[])
    assert len(repos_configuration.indexes) == 1
    assert len(repos_configuration.find_links) == 0

    repos_configuration2 = compute_repos_configuration(parser, args=["--pypi"])
    assert len(repos_configuration2.indexes) == 1
    assert len(repos_configuration2.find_links) == 0

    assert repos_configuration.indexes == repos_configuration2.indexes


def test_clp_find_links_option(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    repos_configuration = compute_repos_configuration(parser, args=["-f", "http://www.example.com"])
    assert len(repos_configuration.indexes) == 1
    assert len(repos_configuration.find_links) == 1


def test_clp_index_option(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    repos_configuration = compute_repos_configuration(parser, args=[])
    assert len(repos_configuration.indexes) == 1
    assert len(repos_configuration.find_links) == 0

    repos_configuration2 = compute_repos_configuration(
        parser, args=["-i", "http://www.example.com"]
    )
    assert len(repos_configuration2.indexes) == 2
    assert len(repos_configuration2.find_links) == 0

    assert repos_configuration2.indexes[0] == repos_configuration.indexes[0]
    assert repos_configuration2.indexes[1] == "http://www.example.com"


def test_clp_index_option_render(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    repos_configuration = compute_repos_configuration(
        parser, args=["--index", "http://www.example.com"]
    )
    assert (resolver_configuration.PYPI, "http://www.example.com") == repos_configuration.indexes
    assert () == repos_configuration.find_links


def test_clp_build_precedence(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    pip_configuration = compute_pip_configuration(parser, args=["--no-build"])
    assert not pip_configuration.build_configuration.allow_builds

    pip_configuration = compute_pip_configuration(parser, args=["--build"])
    assert pip_configuration.build_configuration.allow_builds

    pip_configuration = compute_pip_configuration(parser, args=["--no-wheel"])
    assert not pip_configuration.build_configuration.allow_wheels

    pip_configuration = compute_pip_configuration(parser, args=["--wheel"])
    assert pip_configuration.build_configuration.allow_wheels


def test_pex_repository(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser, include_pex_repository=True)

    resolver_configuration = compute_resolver_configuration(
        parser, args=["--pex-repository", "a.pex"]
    )
    assert isinstance(resolver_configuration, PexRepositoryConfiguration)
    assert "a.pex" == resolver_configuration.pex_repository


def test_pre_resolved_dists(
    tmpdir,  # type: Any
    parser,  # type: ArgumentParser
):
    # type: (...) -> None
    resolver_options.register(parser, include_pre_resolved=True)

    sdist = touch(os.path.join(str(tmpdir), "fake-1.0.tar.gz"))
    expected_sdists = [sdist]

    wheel = touch(os.path.join(str(tmpdir), "fake-1.0.py2.py3-none-any.whl"))
    expected_wheels = [wheel]

    dists_dir = os.path.join(str(tmpdir), "dists")
    touch(os.path.join(dists_dir, "README.md"))
    expected_wheels.append(touch(os.path.join(dists_dir, "another-2.0.py3-non-any.whl")))
    expected_sdists.append(touch(os.path.join(dists_dir, "another-2.0.tar.gz")))
    expected_sdists.append(touch(os.path.join(dists_dir, "one_more-3.0.tar.gz")))

    resolver_configuration = compute_resolver_configuration(
        parser,
        args=[
            "--pre-resolved-dist",
            sdist,
            "--pre-resolved-dist",
            wheel,
            "--pre-resolved-dists",
            dists_dir,
        ],
    )
    assert isinstance(resolver_configuration, PreResolvedConfiguration)
    assert sorted(expected_sdists) == sorted(resolver_configuration.sdists)
    assert sorted(expected_wheels) == sorted(resolver_configuration.wheels)


def test_invalid_configuration(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser, include_pex_repository=True)

    with pytest.raises(resolver_options.InvalidConfigurationError):
        compute_resolver_configuration(
            parser, args=["--pex-repository", "a.pex", "-f", "https://a.find/links/repo"]
        )


def test_vendored_pip_version(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    pip_configuration = compute_pip_configuration(parser, args=["--pip-version", "vendored"])
    assert pip_configuration.version is PipVersion.VENDORED

    pip_configuration = compute_pip_configuration(parser, args=["--pip-version", "20.3.4-patched"])
    assert pip_configuration.version is PipVersion.VENDORED


def test_latest_pip_version(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    pip_configuration = compute_pip_configuration(parser, args=["--pip-version", "latest"])
    assert pip_configuration.version is PipVersion.LATEST


def test_resolver_version_invalid(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    with pytest.raises(resolver_options.InvalidConfigurationError):
        compute_pip_configuration(
            parser, args=["--pip-version", "23.2", "--resolver-version", "pip-legacy-resolver"]
        )


def test_build_configuration_default(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    build_configuration = compute_build_configuration(parser, args=[])
    assert PipConfiguration().build_configuration == build_configuration
    assert BuildConfiguration() == build_configuration


def test_build_configuration_invalid_no_builds_no_wheels(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    with pytest.raises(
        BuildConfiguration.Error,
        match=re.escape(
            "Cannot both disallow builds and disallow wheels. Please allow one of these or both so "
            "that some distributions can be resolved."
        ),
    ):
        compute_build_configuration(parser, args=["--no-build", "--no-wheel"])


def test_build_configuration_invalid_no_builds_only_build(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    with pytest.raises(
        BuildConfiguration.Error,
        match=re.escape(
            "Builds were disallowed, but the following project names are configured to only allow "
            "building: ansicolors"
        ),
    ):
        compute_build_configuration(parser, args=["--no-build", "--only-build", "ansicolors"])


def test_build_configuration_invalid_no_wheels_only_wheel(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    with pytest.raises(
        BuildConfiguration.Error,
        match=re.escape(
            "Resolving wheels was disallowed, but the following project names are configured to "
            "only allow resolving pre-built wheels: ansicolors, cowsay"
        ),
    ):
        compute_build_configuration(
            parser, args=["--no-wheel", "--only-wheel", "cowsay", "--only-wheel", "ansicolors"]
        )


def test_build_configuration_invalid_only_build_only_wheel(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    with pytest.raises(
        BuildConfiguration.Error,
        match=re.escape(
            "The following project names were specified as only being allowed to be built and only "
            "allowed to be resolved as pre-built wheels, please pick one or the other for each: "
            "cowsay"
        ),
    ):
        compute_build_configuration(
            parser,
            args=["--only-wheel", "cowsay", "--only-wheel", "ansicolors", "--only-build", "cowsay"],
        )


def test_build_configuration_warn_prefer_older_binary_unused(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    with pytest.warns(
        PEXWarning,
        match=re.escape(
            "The prefer older binary setting was requested, but this has no effect unless both "
            "pre-built wheels and sdist builds are allowed."
        ),
    ):
        build_configuration = compute_build_configuration(
            parser, args=["--prefer-binary", "--no-build"]
        )
        assert not build_configuration.allow_builds
        assert build_configuration.prefer_older_binary

    with pytest.warns(
        PEXWarning,
        match=re.escape(
            "The prefer older binary setting was requested, but this has no effect unless both "
            "pre-built wheels and sdist builds are allowed."
        ),
    ):
        build_configuration = compute_build_configuration(
            parser, args=["--prefer-binary", "--no-wheel"]
        )
        assert not build_configuration.allow_wheels
        assert build_configuration.prefer_older_binary


def test_build_configuration_warn_use_pep517_no_build(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    with pytest.warns(
        PEXWarning,
        match=re.escape(
            "Use of PEP-517 builds was set to True, but builds are turned off; so this setting has "
            "no effect."
        ),
    ):
        build_configuration = compute_build_configuration(
            parser, args=["--use-pep517", "--no-build"]
        )
        assert not build_configuration.allow_builds
        assert build_configuration.use_pep517


def test_build_configuration_warn_no_build_isolation_no_build(parser):
    # type: (ArgumentParser) -> None
    resolver_options.register(parser)

    with pytest.warns(
        PEXWarning,
        match=re.escape(
            "Build isolation was turned off, but builds are also turned off; so this setting has "
            "no effect."
        ),
    ):
        build_configuration = compute_build_configuration(
            parser, args=["--no-build-isolation", "--no-build"]
        )
        assert not build_configuration.allow_builds
        assert not build_configuration.build_isolation
