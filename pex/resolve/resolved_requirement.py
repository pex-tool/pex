# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib

from pex import hashing
from pex.compatibility import url_unquote, urlparse
from pex.dist_metadata import ProjectNameAndVersion, Requirement
from pex.hashing import HashlibHasher
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.requirements import ArchiveScheme, VCSScheme, parse_scheme
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import BinaryIO, Iterator, Optional, Tuple, Union

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


@attr.s(frozen=True)
class Fingerprint(object):
    @classmethod
    def from_stream(
        cls,
        stream,  # type: BinaryIO
        algorithm="sha256",  # type: str
    ):
        # type: (...) -> Fingerprint
        digest = hashlib.new(algorithm)
        hashing.update_hash(filelike=stream, digest=digest)
        return cls(algorithm=algorithm, hash=digest.hexdigest())

    @classmethod
    def from_digest(cls, digest):
        # type: (HashlibHasher) -> Fingerprint
        return cls.from_hashing_fingerprint(digest.hexdigest())

    @classmethod
    def from_hashing_fingerprint(cls, fingerprint):
        # type: (hashing.Fingerprint) -> Fingerprint
        return cls(algorithm=fingerprint.algorithm, hash=fingerprint)

    algorithm = attr.ib()  # type: str
    hash = attr.ib()  # type: str


@attr.s(frozen=True)
class ArtifactURL(object):
    @classmethod
    def parse(cls, url):
        # type: (str) -> ArtifactURL
        url_info = urlparse.urlparse(url)
        normalized_url = urlparse.urlunparse(
            (url_info.scheme, url_info.netloc, url_unquote(url_info.path).rstrip(), "", "", "")
        )
        return cls(
            raw_url=url,
            normalized_url=normalized_url,
            scheme=parse_scheme(url_info.scheme) if url_info.scheme else None,
            path=url_unquote(url_info.path),
        )

    raw_url = attr.ib(eq=False)  # type: str
    normalized_url = attr.ib()  # type: str
    scheme = attr.ib()  # type: Optional[Union[str, ArchiveScheme.Value, VCSScheme]]
    path = attr.ib(eq=False)  # type: str

    @property
    def is_wheel(self):
        return self.path.endswith(".whl")


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


@attr.s(frozen=True)
class ResolvedRequirement(object):
    pin = attr.ib()  # type: Pin
    artifact = attr.ib()  # type: PartialArtifact
    requirement = attr.ib()  # type: Requirement
    additional_artifacts = attr.ib(default=())  # type: Tuple[PartialArtifact, ...]
    via = attr.ib(default=())  # type: Tuple[str, ...]

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
