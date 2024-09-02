# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import os.path
import warnings

import pytest

from pex.dependency_configuration import DependencyConfiguration
from pex.dependency_manager import DependencyManager
from pex.dist_metadata import Distribution, Requirement
from pex.exceptions import reportable_unexpected_error_msg
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.pex_warnings import PEXWarning
from pex.typing import TYPE_CHECKING
from testing.dist_metadata import create_dist_metadata

if TYPE_CHECKING:
    from typing import Any, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class DistFactory(object):
    install_base_dir = attr.ib()  # type: str

    def create(
        self,
        name,  # type: str
        *requires  # type: str
    ):
        # type: (...) -> FingerprintedDistribution
        fingerprint = hashlib.sha256(name.encode("utf-8")).hexdigest()
        location = os.path.join(self.install_base_dir, fingerprint, name)
        os.makedirs(location)
        return FingerprintedDistribution(
            distribution=Distribution(
                location=location,
                metadata=create_dist_metadata(
                    project_name=name, version="0.1.0", requires_dists=requires, location=location
                ),
            ),
            fingerprint=fingerprint,
        )


@pytest.fixture
def dist_factory(tmpdir):
    # type: (Any) -> DistFactory
    return DistFactory(os.path.join(str(tmpdir), "dists"))


@attr.s(frozen=True)
class DistGraph(object):
    root_reqs = attr.ib()  # type: Tuple[Requirement, ...]
    dists = attr.ib()  # type: Tuple[FingerprintedDistribution, ...]

    def dist(self, name):
        # type: (str) -> FingerprintedDistribution
        project_name = ProjectName(name)
        dists = [
            dist for dist in self.dists if project_name == dist.distribution.metadata.project_name
        ]
        assert len(dists) == 1, "Expected {name} to match one dist, found {found}".format(
            name=name, found=" ".join(map(str, dists)) if dists else "none"
        )
        return dists[0]


@pytest.fixture
def dist_graph(dist_factory):
    # type: (DistFactory) -> DistGraph

    # distA     distB <--------\
    #      \   /     \         |
    #       v v       v        |
    #      distC     distD  (cycle)
    #     /     \   /          |
    #    V       v v           |
    # distE     distF ---------/

    return DistGraph(
        root_reqs=(Requirement.parse("a"), Requirement.parse("b")),
        dists=(
            dist_factory.create("A", "c"),
            dist_factory.create("B", "c", "d"),
            dist_factory.create("C", "e", "f"),
            dist_factory.create("D", "f"),
            dist_factory.create("E"),
            dist_factory.create("F", "b"),
        ),
    )


def test_exclude_root_reqs(dist_graph):
    # type: (DistGraph) -> None

    dependency_manager = DependencyManager(
        requirements=OrderedSet(dist_graph.root_reqs), distributions=OrderedSet(dist_graph.dists)
    )

    pex_info = PexInfo.default()
    pex_builder = PEXBuilder(pex_info=pex_info)

    with warnings.catch_warnings(record=True) as events:
        dependency_manager.configure(
            pex_builder, dependency_configuration=DependencyConfiguration.create(["a", "b"])
        )
    assert 2 == len(events)

    warning = events[0]
    assert PEXWarning == warning.category
    assert (
        "The distribution A 0.1.0 was required by the input requirement a but ultimately excluded "
        "by configured excludes: a"
    ) == str(warning.message)

    warning = events[1]
    assert PEXWarning == warning.category
    assert (
        "The distribution B 0.1.0 was required by the input requirement b but ultimately excluded "
        "by configured excludes: b"
    ) == str(warning.message)

    pex_builder.freeze()

    assert ["a", "b"] == list(pex_info.requirements)
    assert ["a", "b"] == list(pex_info.excluded)
    assert sorted(("C", "D", "E", "F")) == sorted(pex_info.distributions), (
        "The dependency manager should have excluded the root reqs itself but relied on deep "
        "excludes plumbed to Pip to exclude transitive dependencies of the roots."
    )


def test_exclude_transitive_assert(dist_graph):
    # type: (DistGraph) -> None

    dependency_manager = DependencyManager(
        requirements=OrderedSet(dist_graph.root_reqs), distributions=OrderedSet(dist_graph.dists)
    )

    pex_info = PexInfo.default()
    pex_builder = PEXBuilder(pex_info=pex_info)
    with pytest.raises(AssertionError) as exec_info:
        dependency_manager.configure(
            pex_builder, dependency_configuration=DependencyConfiguration.create(["c"])
        )
    assert reportable_unexpected_error_msg(
        "The deep --exclude mechanism failed to exclude C 0.1.0 from transitive requirements. "
        "It should have been excluded by configured excludes: c but was not."
    ) in str(exec_info.value), str(exec_info.value)

    dependency_manager = DependencyManager(
        requirements=OrderedSet(dist_graph.root_reqs),
        distributions=OrderedSet((dist_graph.dist(name) for name in ("A", "B", "D", "F"))),
    )
    dependency_manager.configure(
        pex_builder, dependency_configuration=DependencyConfiguration.create(["c"])
    )
    pex_builder.freeze()

    assert ["a", "b"] == list(pex_info.requirements)
    assert ["c"] == list(pex_info.excluded)
    expected_dists = [dist_graph.dist(name) for name in ("A", "B", "D", "F")]
    assert {
        os.path.basename(dist.location): dist.fingerprint for dist in expected_dists
    } == pex_info.distributions
