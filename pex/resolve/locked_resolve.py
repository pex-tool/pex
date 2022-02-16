# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib

from pex.dist_metadata import ProjectNameAndVersion
from pex.enum import Enum
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.sorted_tuple import SortedTuple
from pex.third_party.packaging import tags
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper

if TYPE_CHECKING:
    from typing import IO, Any, BinaryIO, Iterable, Iterator, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class LockStyle(Enum["LockStyle.Value"]):
    class Value(Enum.Value):
        pass

    STRICT = Value("strict")
    SOURCES = Value("sources")
    UNIVERSAL = Value("universal")


@attr.s(frozen=True)
class LockConfiguration(object):
    style = attr.ib()  # type: LockStyle.Value
    requires_python = attr.ib(default=())  # type: Tuple[str, ...]

    @requires_python.validator
    def _validate_requires_python(
        self,
        _attribute,  # type: Any
        value,  # type: Tuple[str, ...]
    ):
        if len(value) > 0 and self.style != LockStyle.UNIVERSAL:
            raise ValueError(
                "The requires_python field should only be populated for {universal} style locks; "
                "this lock is {style} style and given requires_python of {requires_python}".format(
                    universal=LockStyle.UNIVERSAL.value,
                    style=self.style.value,
                    requires_python=value,
                )
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
        CacheHelper.update_hash(filelike=stream, digest=digest)
        return cls(algorithm=algorithm, hash=digest.hexdigest())

    algorithm = attr.ib()  # type: str
    hash = attr.ib()  # type: str


@attr.s(frozen=True)
class Artifact(object):
    url = attr.ib()  # type: str
    fingerprint = attr.ib()  # type: Fingerprint


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
        requires_dists=(),  # type: Iterable[Requirement]
        requires_python=None,  # type: Optional[SpecifierSet]
        additional_artifacts=(),  # type: Iterable[Artifact]
    ):
        # type: (...) -> LockedRequirement
        return cls(
            pin=pin,
            artifact=artifact,
            requires_dists=SortedTuple(requires_dists, key=lambda req: str(req)),
            requires_python=requires_python,
            additional_artifacts=SortedTuple(additional_artifacts),
        )

    pin = attr.ib()  # type: Pin
    artifact = attr.ib()  # type: Artifact
    requires_dists = attr.ib(default=SortedTuple())  # type: SortedTuple[Requirement]
    requires_python = attr.ib(default=None)  # type: Optional[SpecifierSet]
    additional_artifacts = attr.ib(default=SortedTuple())  # type: SortedTuple[Artifact]

    def iter_artifacts(self):
        # type: () -> Iterator[Artifact]
        yield self.artifact
        for artifact in self.additional_artifacts:
            yield artifact


@attr.s(frozen=True)
class LockedResolve(object):
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
                "    --hash={algorithm}:{hash} {line_continuation}\n".format(
                    algorithm=artifact.fingerprint.algorithm,
                    hash=artifact.fingerprint.hash,
                    line_continuation=" \\" if line_continuation else "",
                )
            )

        for locked_requirement in self.locked_requirements:
            stream.write(
                "{project_name}=={version} \\\n".format(
                    project_name=locked_requirement.pin.project_name,
                    version=locked_requirement.pin.version,
                )
            )
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
