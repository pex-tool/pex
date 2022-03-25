# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import os

import pytest

from pex import dist_metadata, resolver, targets
from pex.resolve.locked_resolve import LockConfiguration, LockStyle
from pex.resolve.resolved_requirement import Pin
from pex.resolve.testing import normalize_locked_resolve
from pex.resolver import Downloaded, LocalDistribution
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper

if TYPE_CHECKING:
    from typing import Any, Dict, Iterable

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def normalize_local_dist(local_dist):
    # type: (LocalDistribution) -> LocalDistribution

    # Each download uses unique temporary dirs as download targets, so paths vary.
    return attr.evolve(local_dist, path=os.path.basename(local_dist.path))


def normalize(
    downloaded,  # type: Downloaded
    skip_additional_artifacts=False,  # type: bool
    skip_urls=False,  # type: bool
    skip_verified=False,  # type: bool
):
    # type: (...) -> Downloaded
    return attr.evolve(
        downloaded,
        local_distributions=tuple(
            sorted(
                normalize_local_dist(local_dist) for local_dist in downloaded.local_distributions
            )
        ),
        locked_resolves=tuple(
            sorted(
                normalize_locked_resolve(
                    lock,
                    skip_additional_artifacts=skip_additional_artifacts,
                    skip_urls=skip_urls,
                    skip_verified=skip_verified,
                )
                for lock in downloaded.locked_resolves
            )
        ),
    )


@pytest.mark.parametrize(
    "requirements",
    (
        pytest.param(["ansicolors==1.1.8"], id="pinned-no-transitive-deps"),
        pytest.param(["isort==4.3.21"], id="pinned-transitive-deps"),
        pytest.param(["ansicolors"], id="float-no-transitive-deps"),
        pytest.param(["isort"], id="float-transitive-deps"),
    ),
)
@pytest.mark.parametrize(
    "lock_configuration",
    (
        pytest.param(LockConfiguration(style=LockStyle.STRICT), id="strict"),
        pytest.param(LockConfiguration(style=LockStyle.SOURCES), id="sources"),
    ),
)
def test_lock_single_target(
    tmpdir,  # type: Any
    requirements,  # type: Iterable[str]
    lock_configuration,  # type: LockConfiguration
):
    # type: (...) -> None

    downloaded = resolver.download(requirements=requirements, lock_configuration=lock_configuration)

    assert 1 == len(downloaded.locked_resolves)
    lock = downloaded.locked_resolves[0]

    assert targets.current().platform.tag == lock.platform_tag

    def pin(local_distribution):
        # type: (LocalDistribution) -> Pin
        project_name_and_version = dist_metadata.project_name_and_version(local_distribution.path)
        assert project_name_and_version is not None
        return Pin.canonicalize(project_name_and_version)

    local_distributions_by_pin = {
        pin(local_dist): local_dist for local_dist in downloaded.local_distributions
    }  # type: Dict[Pin, LocalDistribution]

    assert sorted(local_distributions_by_pin) == sorted(
        locked_req.pin for locked_req in lock.locked_requirements
    ), (
        "Expected the actual set of downloaded distributions to match the set of pinned "
        "requirements in the lock."
    )

    for locked_req in lock.locked_requirements:
        fingerprint = locked_req.artifact.fingerprint
        assert fingerprint.hash == CacheHelper.hash(
            path=local_distributions_by_pin[locked_req.pin].path,
            hasher=lambda: hashlib.new(fingerprint.algorithm),
        ), (
            "Expected the fingerprint of the downloaded distribution to match the fingerprint "
            "recorded in the lock."
        )

    find_links_repo = os.path.join(str(tmpdir), "find-links")
    os.mkdir(find_links_repo)
    for local_dist in downloaded.local_distributions:
        os.symlink(
            local_dist.path, os.path.join(find_links_repo, os.path.basename(local_dist.path))
        )
    assert normalize(
        downloaded, skip_additional_artifacts=True, skip_urls=True, skip_verified=True
    ) == normalize(
        resolver.download(
            requirements=requirements,
            lock_configuration=lock_configuration,
            indexes=[],
            find_links=[find_links_repo],
        ),
        skip_additional_artifacts=True,
        skip_urls=True,
        skip_verified=True,
    ), (
        "Expected a find-links lock to match an equivalent PyPI lock except for the primary "
        "artifact urls and their verification status and lack of additional artifacts (since these "
        "are never downloaded; but instead, just recorded)."
    )

    lock_file = os.path.join(str(tmpdir), "requirements.txt")
    with open(lock_file, "w") as fp:
        lock.emit_requirements(fp)
    assert normalize(downloaded) == normalize(
        resolver.download(requirement_files=[lock_file], lock_configuration=lock_configuration),
    ), (
        "Expected the download used to create a lock to be reproduced by a download using the "
        "requirements generated from the lock."
    )
