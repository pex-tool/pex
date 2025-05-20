# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.artifact_url import ArtifactURL, Fingerprint
from pex.dist_metadata import ProjectNameAndVersion, Requirement
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterator, Optional, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Pin(object):
    @classmethod
    def canonicalize(cls, project_name_and_version):
        # type: (ProjectNameAndVersion) -> Pin
        return cls(
            project_name=ProjectName(project_name_and_version.project_name),
            version=Version(project_name_and_version.version),
        )

    project_name = attr.ib()  # type: ProjectName
    version = attr.ib()  # type: Version

    def as_requirement(self):
        # type: () -> Requirement
        return Requirement.parse(
            "{project_name}=={version}".format(project_name=self.project_name, version=self.version)
        )

    def __str__(self):
        # type: () -> str
        return "{project_name} {version}".format(
            project_name=self.project_name, version=self.version
        )


def _convert_url(value):
    # type: (Union[str, ArtifactURL]) -> ArtifactURL
    if isinstance(value, ArtifactURL):
        return value
    return ArtifactURL.parse(value)


@attr.s(frozen=True)
class PartialArtifact(object):
    url = attr.ib(converter=_convert_url)  # type: ArtifactURL
    fingerprint = attr.ib(default=None)  # type: Optional[Fingerprint]
    verified = attr.ib(default=False)  # type: bool
    commit_id = attr.ib(default=None)  # type: Optional[str]
    editable = attr.ib(default=False)  # type: bool


@attr.s(frozen=True)
class ResolvedRequirement(object):
    pin = attr.ib()  # type: Pin
    artifact = attr.ib()  # type: PartialArtifact
    additional_artifacts = attr.ib(default=())  # type: Tuple[PartialArtifact, ...]

    def iter_artifacts(self):
        # type: () -> Iterator[PartialArtifact]
        yield self.artifact
        for artifact in self.additional_artifacts:
            yield artifact

    def iter_artifacts_to_fingerprint(self):
        # type: () -> Iterator[PartialArtifact]
        for artifact in self.iter_artifacts():
            if not artifact.fingerprint:
                yield artifact
