# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools

from pex.dist_metadata import DistMetadata
from pex.enum import Enum
from pex.fetcher import URLFetcher
from pex.resolve.resolved_requirement import Fingerprint, PartialArtifact, Pin, ResolvedRequirement
from pex.sorted_tuple import SortedTuple
from pex.third_party.packaging import tags
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import IO, Any, Callable, Iterable, Iterator, Optional, Tuple

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
class LockRequest(object):
    lock_configuration = attr.ib()  # type: LockConfiguration
    resolve_handler = attr.ib()  # type: Callable[[Iterable[ResolvedRequirement]], None]


@attr.s(frozen=True)
class Artifact(object):
    url = attr.ib()  # type: str
    fingerprint = attr.ib()  # type: Fingerprint


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
    @classmethod
    def create(
        cls,
        platform_tag,  # type: tags.Tag
        resolved_requirements,  # type: Iterable[ResolvedRequirement]
        dist_metadatas,  # type: Iterable[DistMetadata]
        url_fetcher,  # type: URLFetcher
    ):
        # type: (...) -> LockedResolve

        # TODO(John Sirois): Introduce a thread pool and pump these fetches to workers via a Queue.
        def fingerprint_url(url):
            # type: (str) -> Fingerprint
            with url_fetcher.get_body_stream(url) as body_stream:
                return Fingerprint.from_stream(body_stream)

        fingerprint_by_url = {
            url: fingerprint_url(url)
            for url in set(
                itertools.chain.from_iterable(
                    resolved_requirement._iter_urls_to_fingerprint()
                    for resolved_requirement in resolved_requirements
                )
            )
        }

        def resolve_fingerprint(partial_artifact):
            # type: (PartialArtifact) -> Artifact
            return Artifact(
                url=partial_artifact.url,
                fingerprint=partial_artifact.fingerprint
                or fingerprint_by_url[partial_artifact.url],
            )

        dist_metadata_by_pin = {
            Pin(dist_info.project_name, dist_info.version): dist_info
            for dist_info in dist_metadatas
        }
        locked_requirements = []
        for resolved_requirement in resolved_requirements:
            distribution_metadata = dist_metadata_by_pin.get(resolved_requirement.pin)
            if distribution_metadata is None:
                raise ValueError(
                    "No distribution metadata found for {project}.\n"
                    "Given distribution metadata for:\n"
                    "{projects}".format(
                        project=resolved_requirement.pin.as_requirement(),
                        projects="\n".join(
                            sorted(str(pin.as_requirement()) for pin in dist_metadata_by_pin)
                        ),
                    )
                )
            locked_requirements.append(
                LockedRequirement.create(
                    pin=resolved_requirement.pin,
                    artifact=resolve_fingerprint(resolved_requirement.artifact),
                    requires_dists=distribution_metadata.requires_dists,
                    requires_python=distribution_metadata.requires_python,
                    additional_artifacts=(
                        resolve_fingerprint(artifact)
                        for artifact in resolved_requirement.additional_artifacts
                    ),
                )
            )
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
