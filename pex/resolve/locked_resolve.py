# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib

from pex.dist_metadata import ProjectNameAndVersion
from pex.distribution_target import DistributionTarget
from pex.enum import Enum
from pex.pep_503 import ProjectName
from pex.sorted_tuple import SortedTuple
from pex.third_party.packaging import tags
from pex.third_party.packaging import utils as packaging_utils
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import BinaryIO, IO, Iterable, Iterator, Tuple
else:
    from pex.third_party import attr


class LockStyle(Enum["LockStyle.Value"]):
    class Value(Enum.Value):
        pass

    STRICT = Value("strict")
    SOURCES = Value("sources")


@attr.s(frozen=True)
class LockConfiguration(object):
    style = attr.ib()  # type: LockStyle.Value


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
        CacheHelper.update_hash(filelike=stream, digest=digest)
        return cls(algorithm=algorithm, hash=digest.hexdigest())

    algorithm = attr.ib()  # type: str
    hash = attr.ib()  # type: str


@attr.s(frozen=True)
class Artifact(object):
    url = attr.ib()  # type: str
    fingerprint = attr.ib()  # type: Fingerprint


def _canonicalize_version(version):
    # type: (str) -> str
    return cast(str, packaging_utils.canonicalize_version(version))


@attr.s(frozen=True)
class Version(object):
    version = attr.ib(converter=_canonicalize_version)  # type: str

    def __str__(self):
        # type: () -> str
        return self.version


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


@attr.s(frozen=True)
class LockedRequirement(object):
    @classmethod
    def create(
        cls,
        pin,  # type: Pin
        artifact,  # type: Artifact
        requirement,  # type: Requirement
        additional_artifacts=(),  # type: Iterable[Artifact]
        via=(),  # type: Iterable[str]
    ):
        # type: (...) -> LockedRequirement
        return cls(
            pin=pin,
            artifact=artifact,
            requirement=requirement,
            additional_artifacts=SortedTuple(additional_artifacts),
            via=tuple(via),
        )

    pin = attr.ib()  # type: Pin
    artifact = attr.ib()  # type: Artifact
    requirement = attr.ib(order=str)  # type: Requirement
    additional_artifacts = attr.ib(default=())  # type: SortedTuple[Artifact]
    via = attr.ib(default=())  # type: Tuple[str, ...]

    def iter_artifacts(self):
        # type: () -> Iterator[Artifact]
        yield self.artifact
        for artifact in self.additional_artifacts:
            yield artifact


@attr.s(frozen=True)
class LockedResolve(object):
    @classmethod
    def from_target(
        cls,
        target,  # type: DistributionTarget
        locked_requirements,  # type: Iterable[LockedRequirement]
    ):
        # type: (...) -> LockedResolve
        most_specific_tag = target.get_supported_tags()[0]
        return cls(
            platform_tag=most_specific_tag, locked_requirements=SortedTuple(locked_requirements)
        )

    @classmethod
    def from_platform_tag(
        cls,
        platform_tag,  # type: tags.Tag
        locked_requirements,  # type: Iterable[LockedRequirement]
    ):
        # type: (...) -> LockedResolve
        return cls(platform_tag=platform_tag, locked_requirements=SortedTuple(locked_requirements))

    platform_tag = attr.ib(order=str)  # type: tags.Tag
    locked_requirements = attr.ib()  # type: SortedTuple[LockedRequirement]

    def emit_requirements(self, stream):
        # type: (IO[str]) -> None
        def emit_artifact(
            artifact,  # type: Artifact
            line_continuation,  # type: bool
        ):
            # type: (...) -> None
            stream.write(
                "    --hash:{algorithm}={hash} # {url}{line_continuation}\n".format(
                    algorithm=artifact.fingerprint.algorithm,
                    hash=artifact.fingerprint.hash,
                    url=artifact.url,
                    line_continuation=" \\" if line_continuation else "",
                )
            )

        for locked_requirement in self.locked_requirements:
            stream.write(
                "{project_name}=={version} # {requirement}".format(
                    project_name=locked_requirement.pin.project_name,
                    version=locked_requirement.pin.version,
                    requirement=locked_requirement.requirement,
                )
            )
            if locked_requirement.via:
                stream.write(" via -> {}".format(" via -> ".join(locked_requirement.via)))
            stream.write(" \\\n")
            emit_artifact(
                locked_requirement.artifact,
                line_continuation=bool(locked_requirement.additional_artifacts),
            )
            for index, additional_artifact in enumerate(
                locked_requirement.additional_artifacts, start=1
            ):
                emit_artifact(
                    additional_artifact,
                    line_continuation=index != len(locked_requirement.additional_artifacts),
                )
