# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib

from pex.dist_metadata import ProjectNameAndVersion
from pex.distribution_target import DistributionTarget
from pex.pep_503 import ProjectName
from pex.third_party.packaging import utils as packaging_utils
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import BinaryIO, IO, Tuple
else:
    from pex.third_party import attr


class LockStyle(object):
    class Value(object):
        def __init__(self, value):
            # type: (str) -> None
            self.value = value

        def __str__(self):
            # type: () -> str
            return str(self.value)

        def __repr__(self):
            # type: () -> str
            return repr(self.value)

    STRICT = Value("strict")
    SOURCES = Value("sources")

    values = STRICT, SOURCES

    @classmethod
    def for_value(cls, value):
        # type: (str) -> LockStyle.Value
        for v in cls.values:
            if v.value == value:
                return v
        raise ValueError(
            "{!r} of type {} must be one of {}".format(
                value, type(value), ", ".join(map(repr, cls.values))
            )
        )


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


@attr.s(frozen=True)
class LockedRequirement(object):
    pin = attr.ib()  # type: Pin
    artifact = attr.ib()  # type: Artifact
    requirement = attr.ib()  # type: Requirement
    additional_artifacts = attr.ib(default=())  # type: Tuple[Artifact, ...]
    via = attr.ib(default=())  # type: Tuple[str, ...]


@attr.s(frozen=True)
class LockedResolve(object):
    target = attr.ib()  # type: DistributionTarget
    locked_requirements = attr.ib()  # type: Tuple[LockedRequirement, ...]

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

        for locked_requirement in sorted(self.locked_requirements, key=lambda lr: lr.pin):
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
