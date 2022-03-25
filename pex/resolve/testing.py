# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.resolve.locked_resolve import FileArtifact, LockedRequirement, LockedResolve, VCSArtifact
from pex.sorted_tuple import SortedTuple
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def normalize_artifact(
    artifact,  # type: Union[FileArtifact, VCSArtifact]
    skip_urls=False,  # type: bool
    skip_verified=False,  # type: bool
):
    # type: (...) -> Union[FileArtifact, VCSArtifact]
    return attr.evolve(
        artifact,
        url="" if skip_urls else artifact.url,
        verified=False if skip_verified else artifact.verified,
    )


def normalize_locked_requirement(
    locked_req,  # type: LockedRequirement
    skip_additional_artifacts=False,  # type: bool
    skip_urls=False,  # type: bool
    skip_verified=False,  # type: bool
):
    # type: (...) -> LockedRequirement
    return attr.evolve(
        locked_req,
        artifact=normalize_artifact(
            locked_req.artifact, skip_urls=skip_urls, skip_verified=skip_verified
        ),
        additional_artifacts=()
        if skip_additional_artifacts
        else SortedTuple(
            normalize_artifact(a, skip_urls=skip_urls, skip_verified=skip_verified)
            for a in locked_req.additional_artifacts
        ),
    )


def normalize_locked_resolve(
    lock,  # type: LockedResolve
    skip_additional_artifacts=False,  # type: bool
    skip_urls=False,  # type: bool
    skip_verified=False,  # type: bool
):
    # type: (...) -> LockedResolve
    return attr.evolve(
        lock,
        locked_requirements=SortedTuple(
            normalize_locked_requirement(
                locked_req,
                skip_additional_artifacts=skip_additional_artifacts,
                skip_urls=skip_urls,
                skip_verified=skip_verified,
            )
            for locked_req in lock.locked_requirements
        ),
    )
