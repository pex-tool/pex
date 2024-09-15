# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib

from pex import hashing
from pex.compatibility import url_unquote, urlparse
from pex.dist_metadata import ProjectNameAndVersion, Requirement, is_wheel
from pex.hashing import HashlibHasher
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.requirements import ArchiveScheme, VCSScheme, parse_scheme
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import BinaryIO, Iterator, Mapping, Optional, Sequence, Tuple, Union

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
    # These ranks prefer the highest digest size and then use alphabetic order for a tie-break.

    _RANKED_ALGORITHMS = tuple(
        sorted(
            hashlib.algorithms_guaranteed,
            key=lambda alg: (-hashlib.new(alg).digest_size, alg),
        )
    )

    @classmethod
    def parse(cls, url):
        # type: (str) -> ArtifactURL
        url_info = urlparse.urlparse(url)
        scheme = parse_scheme(url_info.scheme) if url_info.scheme else "file"
        path = url_unquote(url_info.path)

        fingerprints = []
        fragment_parameters = urlparse.parse_qs(url_info.fragment)
        if fragment_parameters:
            # Artifact URLs from indexes may contain pre-computed hashes. We isolate those here,
            # centrally, if present.
            # See: https://peps.python.org/pep-0503/#specification
            for alg in cls._RANKED_ALGORITHMS:
                hashes = fragment_parameters.pop(alg, None)
                if not hashes:
                    continue
                if len(hashes) > 1 and len(set(hashes)) > 1:
                    TRACER.log(
                        "The artifact url contains multiple distinct hash values for the {alg} "
                        "algorithm, not trusting any of these: {url}".format(alg=alg, url=url)
                    )
                    continue
                fingerprints.append(Fingerprint(algorithm=alg, hash=hashes[0]))

        download_url = urlparse.urlunparse(
            url_info._replace(
                fragment="&".join(
                    sorted(
                        "{name}={value}".format(name=name, value=value)
                        for name, values in fragment_parameters.items()
                        for value in values
                    )
                )
            )
        )
        normalized_url = urlparse.urlunparse(
            url_info._replace(path=path, params="", query="", fragment="")
        )
        return cls(
            raw_url=url,
            download_url=download_url,
            normalized_url=normalized_url,
            scheme=scheme,
            path=path,
            fragment_parameters=fragment_parameters,
            fingerprints=tuple(fingerprints),
        )

    raw_url = attr.ib(eq=False)  # type: str
    download_url = attr.ib(eq=False)  # type: str
    normalized_url = attr.ib()  # type: str
    scheme = attr.ib(eq=False)  # type: Union[str, ArchiveScheme.Value, VCSScheme]
    path = attr.ib(eq=False)  # type: str
    fragment_parameters = attr.ib(eq=False)  # type: Mapping[str, Sequence[str]]
    fingerprints = attr.ib(eq=False)  # type: Tuple[Fingerprint, ...]

    @property
    def is_wheel(self):
        # type: () -> bool
        return is_wheel(self.path)

    @property
    def fingerprint(self):
        # type: () -> Optional[Fingerprint]
        return self.fingerprints[0] if self.fingerprints else None


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
