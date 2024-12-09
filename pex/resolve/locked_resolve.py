# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division

import itertools
import os
from collections import OrderedDict, defaultdict, deque
from functools import total_ordering

from pex.common import pluralize
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import DistMetadata, Requirement, is_sdist, is_wheel
from pex.enum import Enum
from pex.orderedset import OrderedSet
from pex.pep_425 import CompatibilityTags, TagRank
from pex.pep_503 import ProjectName
from pex.rank import Rank
from pex.requirements import VCS, VCSScheme
from pex.resolve.resolved_requirement import (
    ArtifactURL,
    Fingerprint,
    PartialArtifact,
    Pin,
    ResolvedRequirement,
)
from pex.resolve.resolver_configuration import BuildConfiguration
from pex.result import Error
from pex.sorted_tuple import SortedTuple
from pex.targets import Target
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import (
        Any,
        DefaultDict,
        Deque,
        Dict,
        Iterable,
        Iterator,
        List,
        Optional,
        Protocol,
        Set,
        Tuple,
        Union,
    )

    import attr  # vendor:skip
    from packaging import tags  # vendor:skip
    from packaging import version as packaging_version  # vendor:skip
    from packaging.specifiers import SpecifierSet  # vendor:skip
else:
    from pex.third_party import attr
    from pex.third_party.packaging import tags
    from pex.third_party.packaging import version as packaging_version
    from pex.third_party.packaging.specifiers import SpecifierSet


class LockStyle(Enum["LockStyle.Value"]):
    class Value(Enum.Value):
        pass

    STRICT = Value("strict")
    SOURCES = Value("sources")
    UNIVERSAL = Value("universal")


LockStyle.seal()


class TargetSystem(Enum["TargetSystem.Value"]):
    class Value(Enum.Value):
        pass

    LINUX = Value("linux")
    MAC = Value("mac")
    WINDOWS = Value("windows")


TargetSystem.seal()


@attr.s(frozen=True)
class LockConfiguration(object):
    style = attr.ib()  # type: LockStyle.Value
    requires_python = attr.ib(default=())  # type: Tuple[str, ...]
    target_systems = attr.ib(default=())  # type: Tuple[TargetSystem.Value, ...]
    elide_unused_requires_dist = attr.ib(default=False)  # type: bool

    @requires_python.validator
    @target_systems.validator
    def _validate_only_set_for_universal(
        self,
        attribute,  # type: Any
        value,  # type: Any
    ):
        if value and self.style != LockStyle.UNIVERSAL:
            raise ValueError(
                "The {field_name} field should only be set for {universal} style locks; "
                "this lock is {style} style and given {field_name} value of {value}".format(
                    field_name=attribute.name,
                    universal=LockStyle.UNIVERSAL.value,
                    style=self.style.value,
                    value=value,
                )
            )


@total_ordering
@attr.s(frozen=True, order=False)
class Artifact(object):
    @classmethod
    def from_artifact_url(
        cls,
        artifact_url,  # type: ArtifactURL
        fingerprint,  # type: Fingerprint
        verified=False,  # type: bool
    ):
        # type: (...) -> Union[FileArtifact, LocalProjectArtifact, VCSArtifact]
        if isinstance(artifact_url.scheme, VCSScheme):
            return VCSArtifact.from_artifact_url(
                artifact_url=artifact_url,
                fingerprint=fingerprint,
                verified=verified,
            )

        if "file" == artifact_url.scheme and os.path.isdir(artifact_url.path):
            directory = os.path.normpath(artifact_url.path)
            return LocalProjectArtifact(
                url=artifact_url,
                fingerprint=fingerprint,
                verified=verified,
                directory=directory,
            )

        filename = os.path.basename(artifact_url.path)
        return FileArtifact(
            url=artifact_url,
            fingerprint=fingerprint,
            verified=verified,
            filename=filename,
        )

    @classmethod
    def from_url(
        cls,
        url,  # type: str
        fingerprint,  # type: Fingerprint
        verified=False,  # type: bool
    ):
        # type: (...) -> Union[FileArtifact, LocalProjectArtifact, VCSArtifact]
        return cls.from_artifact_url(
            artifact_url=ArtifactURL.parse(url), fingerprint=fingerprint, verified=verified
        )

    url = attr.ib()  # type: ArtifactURL
    fingerprint = attr.ib()  # type: Fingerprint
    verified = attr.ib()  # type: bool

    def __lt__(self, other):
        # type: (Any) -> bool
        if not isinstance(other, Artifact):
            return NotImplemented
        return self.url < other.url


@attr.s(frozen=True, order=False)
class FileArtifact(Artifact):
    filename = attr.ib()  # type: str

    @property
    def is_source(self):
        # type: () -> bool
        return is_sdist(self.filename)

    def parse_tags(self):
        # type: () -> Iterator[tags.Tag]
        if is_wheel(self.filename):
            for tag in CompatibilityTags.from_wheel(self.filename):
                yield tag


@attr.s(frozen=True, order=False)
class LocalProjectArtifact(Artifact):
    directory = attr.ib()  # type: str

    @property
    def is_source(self):
        # type: () -> bool
        return True


@attr.s(frozen=True, order=False)
class VCSArtifact(Artifact):
    @classmethod
    def from_artifact_url(
        cls,
        artifact_url,  # type: ArtifactURL
        fingerprint,  # type: Fingerprint
        verified=False,  # type: bool
    ):
        # type: (...) -> VCSArtifact
        if not isinstance(artifact_url.scheme, VCSScheme):
            raise ValueError(
                "The given artifact URL is not that of a VCS artifact: {url}".format(
                    url=artifact_url.raw_url
                )
            )
        return cls(
            url=artifact_url,
            fingerprint=fingerprint,
            verified=verified,
            vcs=artifact_url.scheme.vcs,
        )

    vcs = attr.ib()  # type: VCS.Value

    @property
    def is_source(self):
        return True

    def as_unparsed_requirement(self, project_name):
        # type: (ProjectName) -> str
        names = self.url.fragment_parameters.get("egg")
        if names and ProjectName(names[-1]) == project_name:
            # A Pip proprietary VCS requirement.
            return self.url.raw_url
        # A PEP-440 direct reference VCS requirement with the project name stripped from earlier
        # processing. See: https://peps.python.org/pep-0440/#direct-references
        return "{project_name} @ {url}".format(project_name=project_name, url=self.url.raw_url)


@attr.s(frozen=True)
class RankedArtifact(object):
    artifact = attr.ib()  # type: Union[FileArtifact, LocalProjectArtifact, VCSArtifact]
    rank = attr.ib()  # type: TagRank


@attr.s(frozen=True)
class LockedRequirement(object):
    @classmethod
    def create(
        cls,
        pin,  # type: Pin
        artifact,  # type: Union[FileArtifact, LocalProjectArtifact, VCSArtifact]
        requires_dists=(),  # type: Iterable[Requirement]
        requires_python=None,  # type: Optional[SpecifierSet]
        additional_artifacts=(),  # type: Iterable[Union[FileArtifact, LocalProjectArtifact, VCSArtifact]]
    ):
        # type: (...) -> LockedRequirement
        return cls(
            pin=pin,
            artifact=artifact,
            requires_dists=SortedTuple(requires_dists, key=str),
            requires_python=requires_python,
            additional_artifacts=SortedTuple(additional_artifacts),
        )

    pin = attr.ib()  # type: Pin
    artifact = attr.ib()  # type: Union[FileArtifact, LocalProjectArtifact, VCSArtifact]
    requires_dists = attr.ib(default=SortedTuple())  # type: SortedTuple[Requirement]
    requires_python = attr.ib(default=None)  # type: Optional[SpecifierSet]
    additional_artifacts = attr.ib(
        default=SortedTuple()
    )  # type: SortedTuple[Union[FileArtifact, LocalProjectArtifact, VCSArtifact]]

    def iter_artifacts(self):
        # type: () -> Iterator[Union[FileArtifact, LocalProjectArtifact, VCSArtifact]]
        yield self.artifact
        for artifact in self.additional_artifacts:
            yield artifact

    def iter_compatible_artifacts(
        self,
        target,  # type: Target
        build=True,  # type: bool
        use_wheel=True,  # type: bool
    ):
        # type: (...) -> Iterator[RankedArtifact]
        """Iterate all compatible artifacts for the given target and resolve configuration.

        :param target: The target looking to pick a resolve to use.
        :param build: Whether sdists are allowed.
        :param use_wheel: Whether wheels are allowed.
        :return: The highest ranked artifact if the requirement is compatible with the target else
            `None`.
        """
        for artifact in self.iter_artifacts():
            if build and artifact.is_source:
                # N.B.: Ensure sdists are picked last amongst a set of artifacts. We do this, since
                # a wheel is known to work with a target by the platform tags on the tin, whereas an
                # sdist may not successfully build for a given target at all. This is an affordance
                # for LockStyle.SOURCES and LockStyle.CROSS_PLATFORM lock styles.
                sdist_rank = target.supported_tags.lowest_rank.lower()
                yield RankedArtifact(artifact=artifact, rank=sdist_rank)
            elif use_wheel and isinstance(artifact, FileArtifact):
                for tag in artifact.parse_tags():
                    wheel_rank = target.supported_tags.rank(tag)
                    if wheel_rank is None:
                        continue
                    yield RankedArtifact(artifact=artifact, rank=wheel_rank)


@attr.s(frozen=True)
class _ResolveRequest(object):
    @classmethod
    def root(
        cls,
        target_platform,  # type: str
        requirement,  # type: Requirement
        dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
    ):
        # type: (...) -> _ResolveRequest
        return cls(
            target_platform=target_platform,
            required_by=(requirement,),
            requirement=requirement,
            dependency_configuration=dependency_configuration,
        )

    target_platform = attr.ib()  # type: str
    required_by = attr.ib()  # type: Tuple[Requirement, ...]
    requirement = attr.ib()  # type: Requirement
    extras = attr.ib(default=())  # type: Iterable[str]
    dependency_configuration = attr.ib(
        default=DependencyConfiguration()
    )  # type: DependencyConfiguration

    @property
    def project_name(self):
        # type: () -> ProjectName
        return self.requirement.project_name

    @property
    def excluded(self):
        # type: () -> bool
        return self.is_excluded(self.requirement)

    def is_excluded(self, requirement):
        # type: (Requirement) -> bool
        excluded_by = self.dependency_configuration.excluded_by(requirement)
        if excluded_by:
            TRACER.log(
                "Locked requirement {requirement} from {platform} lock excluded by "
                "{exclude} {excluded_by}.".format(
                    requirement=requirement,
                    exclude=pluralize(excluded_by, "exclude"),
                    excluded_by=" and ".join(map(str, excluded_by)),
                    platform=self.target_platform,
                )
            )
        return bool(excluded_by)

    def request_dependencies(
        self,
        locked_requirement,  # type: LockedRequirement
        target,  # type: Target
    ):
        # type: (...) -> Iterator[_ResolveRequest]
        for requires_dist in locked_requirement.requires_dists:
            if self.is_excluded(requires_dist):
                continue
            override = self.dependency_configuration.overridden_by(requires_dist, target=target)
            if override:
                TRACER.log(
                    "Dependency {requirement} of locked project {project} from {platform} lock "
                    "overridden by {override}.".format(
                        requirement=requires_dist,
                        project=locked_requirement.pin,
                        platform=self.target_platform,
                        override=override,
                    )
                )
                requires_dist = override
            yield _ResolveRequest(
                target_platform=self.target_platform,
                required_by=self.required_by + (requires_dist,),
                requirement=requires_dist,
                extras=self.requirement.extras,
                dependency_configuration=self.dependency_configuration,
            )

    def render_via(self):
        # type: () -> str
        return "via: {via}".format(via=" -> ".join(map(str, self.required_by)))


@attr.s(frozen=True)
class _ResolvedArtifact(object):
    ranked_artifact = attr.ib()  # type: RankedArtifact
    locked_requirement = attr.ib()  # type: LockedRequirement

    @property
    def artifact(self):
        # type: () -> Union[FileArtifact, LocalProjectArtifact, VCSArtifact]
        return self.ranked_artifact.artifact

    @property
    def version(self):
        # type: () -> Union[packaging_version.LegacyVersion, packaging_version.Version]
        return self.locked_requirement.pin.version.parsed_version

    def select_higher_rank(
        self,
        other,  # type: _ResolvedArtifact
        prefer_older_binary=False,  # type: bool
    ):
        # type: (...) -> _ResolvedArtifact

        if prefer_older_binary and self.artifact.is_source ^ other.artifact.is_source:
            return Rank.select_highest_rank(self, other, lambda ra: ra.ranked_artifact.rank)

        if self.version == other.version:
            return Rank.select_highest_rank(self, other, lambda ra: ra.ranked_artifact.rank)
        return self if self.version > other.version else other


@attr.s(frozen=True, order=False)
class _ResolvedArtifactComparator(object):
    resolved_artifact = attr.ib()  # type: _ResolvedArtifact
    prefer_older_binary = attr.ib(default=False)  # type: bool

    def __lt__(self, other):
        # type: (_ResolvedArtifactComparator) -> bool
        highest_ranked = self.resolved_artifact.select_higher_rank(
            other.resolved_artifact, self.prefer_older_binary
        )
        return highest_ranked is other.resolved_artifact


@attr.s(frozen=True)
class DownloadableArtifact(object):
    @classmethod
    def create(
        cls,
        pin,  # type: Pin
        artifact,  # type: Union[FileArtifact, LocalProjectArtifact, VCSArtifact]
        satisfied_direct_requirements=(),  # type: Iterable[Requirement]
    ):
        # type: (...) -> DownloadableArtifact
        return cls(
            pin=pin,
            artifact=artifact,
            satisfied_direct_requirements=SortedTuple(satisfied_direct_requirements, key=str),
        )

    pin = attr.ib()  # type: Pin
    artifact = attr.ib()  # type: Union[FileArtifact, LocalProjectArtifact, VCSArtifact]
    satisfied_direct_requirements = attr.ib(default=SortedTuple())  # type: SortedTuple[Requirement]


@attr.s(frozen=True)
class Resolved(object):
    @classmethod
    def create(
        cls,
        target,  # type: Target
        direct_requirements,  # type: Iterable[Requirement]
        resolved_artifacts,  # type: Iterable[_ResolvedArtifact]
        source,  # type: LockedResolve
    ):
        # type: (...) -> Resolved

        direct_requirements_by_project_name = defaultdict(
            list
        )  # type: DefaultDict[ProjectName, List[Requirement]]
        for requirement in direct_requirements:
            direct_requirements_by_project_name[requirement.project_name].append(requirement)

        # N.B.: Lowest rank means highest rank value. I.E.: The 1st tag is the most specific and
        # the 765th tag is the least specific.
        largest_rank_value = target.supported_tags.lowest_rank.value
        smallest_rank_value = TagRank.highest_natural().value
        rank_span = largest_rank_value - smallest_rank_value

        downloadable_artifacts = []
        target_specificities = []
        for resolved_artifact in resolved_artifacts:
            pin = resolved_artifact.locked_requirement.pin
            downloadable_artifacts.append(
                DownloadableArtifact.create(
                    pin=pin,
                    artifact=resolved_artifact.artifact,
                    satisfied_direct_requirements=direct_requirements_by_project_name[
                        pin.project_name
                    ],
                )
            )
            target_specificities.append(
                (rank_span - (resolved_artifact.ranked_artifact.rank.value - smallest_rank_value))
                / rank_span
            )

        return cls(
            target_specificity=(
                smallest_rank_value
                if not target_specificities
                else sum(target_specificities) / len(target_specificities)
            ),
            downloadable_artifacts=tuple(downloadable_artifacts),
            source=source,
        )

    @classmethod
    def most_specific(cls, resolves):
        # type: (Iterable[Resolved]) -> Resolved
        sorted_resolves = sorted(resolves)
        if len(sorted_resolves) == 0:
            raise ValueError("Given no resolves to pick from.")
        # The most specific has the highest specificity which sorts last.
        return sorted_resolves[-1]

    target_specificity = attr.ib()  # type: float
    downloadable_artifacts = attr.ib()  # type: Tuple[DownloadableArtifact, ...]
    source = attr.ib(eq=False)  # type: LockedResolve


if TYPE_CHECKING:

    class Fingerprinter(Protocol):
        def fingerprint(self, artifacts):
            # type: (Iterable[PartialArtifact]) -> Iterator[FileArtifact]
            pass


@attr.s(frozen=True)
class LockedResolve(object):
    @classmethod
    def create(
        cls,
        resolved_requirements,  # type: Iterable[ResolvedRequirement]
        dist_metadatas,  # type: Iterable[DistMetadata]
        fingerprinter,  # type: Fingerprinter
        platform_tag=None,  # type: Optional[tags.Tag]
    ):
        # type: (...) -> LockedResolve

        artifacts_to_fingerprint = OrderedSet(
            itertools.chain.from_iterable(
                resolved_requirement.iter_artifacts_to_fingerprint()
                for resolved_requirement in resolved_requirements
            )
        )
        file_artifact_by_partial_artifact = dict(
            zip(
                artifacts_to_fingerprint,
                tuple(fingerprinter.fingerprint(artifacts_to_fingerprint)),
            )
        )

        def resolve_fingerprint(partial_artifact):
            # type: (PartialArtifact) -> Union[FileArtifact, LocalProjectArtifact, VCSArtifact]
            file_artifact = file_artifact_by_partial_artifact.get(partial_artifact)
            if file_artifact:
                return file_artifact
            assert partial_artifact.fingerprint is not None, (
                "No FileArtifact for {partial_artifact} mapped:\n"
                "{mapping}\n"
                "to_map:\n"
                "{to_map}".format(
                    partial_artifact=partial_artifact,
                    mapping="\n".join(map(str, file_artifact_by_partial_artifact.items())),
                    to_map="\n".join(map(str, artifacts_to_fingerprint)),
                )
            )
            return Artifact.from_artifact_url(
                artifact_url=partial_artifact.url,
                fingerprint=partial_artifact.fingerprint,
                verified=partial_artifact.verified,
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
        return cls(locked_requirements=SortedTuple(locked_requirements), platform_tag=platform_tag)

    locked_requirements = attr.ib()  # type: SortedTuple[LockedRequirement]
    platform_tag = attr.ib(order=str, default=None)  # type: Optional[tags.Tag]

    @property
    def target_platform(self):
        # type: () -> str
        return str(self.platform_tag) if self.platform_tag else "universal"

    def resolve(
        self,
        target,  # type: Target
        requirements,  # type: Iterable[Requirement]
        constraints=(),  # type: Iterable[Requirement]
        source=None,  # type: Optional[str]
        transitive=True,  # type: bool
        build_configuration=BuildConfiguration(),  # type: BuildConfiguration
        include_all_matches=False,  # type: bool
        dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
    ):
        # type: (...) -> Union[Resolved, Error]

        repository = defaultdict(list)  # type: DefaultDict[ProjectName, List[LockedRequirement]]
        for locked_requirement in self.locked_requirements:
            repository[locked_requirement.pin.project_name].append(locked_requirement)

        # 1. Gather all required projects and their requirers.
        required = OrderedDict()  # type: OrderedDict[ProjectName, List[_ResolveRequest]]
        to_be_resolved = deque()  # type: Deque[_ResolveRequest]

        def request_resolve(requests):
            # type: (Iterable[_ResolveRequest]) -> None
            to_be_resolved.extend(
                request
                for request in requests
                if not request.excluded
                and target.requirement_applies(request.requirement, extras=request.extras)
            )

        resolved = {}  # type: Dict[ProjectName, Set[str]]

        request_resolve(
            _ResolveRequest.root(
                self.target_platform, requirement, dependency_configuration=dependency_configuration
            )
            for requirement in requirements
        )
        while to_be_resolved:
            resolve_request = to_be_resolved.popleft()
            project_name = resolve_request.project_name
            required.setdefault(project_name, []).append(resolve_request)

            if not transitive:
                continue

            required_extras = set(resolve_request.requirement.extras)
            if project_name not in resolved:
                resolved[project_name] = required_extras
            else:
                resolved_extras = resolved[project_name]
                if required_extras.issubset(resolved_extras):
                    continue
                resolved_extras.update(required_extras)

            for locked_requirement in repository[project_name]:
                request_resolve(
                    resolve_request.request_dependencies(locked_requirement, target=target)
                )

        # 2. Select either the best fit artifact for each requirement or collect an error.
        constraints_by_project_name = {
            constraint.project_name: constraint for constraint in constraints
        }
        resolved_artifacts = []  # type: List[_ResolvedArtifact]
        errors = []
        for project_name, resolve_requests in required.items():
            reasons = []  # type: List[str]
            compatible_artifacts = []  # type: List[_ResolvedArtifact]
            for locked_requirement in repository[project_name]:

                def attributed_reason(reason):
                    # type: (str) -> str
                    if len(resolve_requests) == 1:
                        return "{pin} ({via}) {reason}".format(
                            pin=locked_requirement.pin,
                            via=resolve_requests[0].render_via(),
                            reason=reason,
                        )
                    return (
                        "{pin} {reason}\n"
                        "    requirers:\n"
                        "    {vias}".format(
                            pin=locked_requirement.pin,
                            reason=reason,
                            vias="\n    ".join(rr.render_via() for rr in resolve_requests),
                        )
                    )

                if locked_requirement.requires_python and not target.requires_python_applies(
                    locked_requirement.requires_python,
                    source=locked_requirement.pin.as_requirement(),
                ):
                    reasons.append(
                        attributed_reason(
                            "requires Python {specifier}".format(
                                specifier=locked_requirement.requires_python,
                            )
                        )
                    )
                    continue

                version_mismatches = []
                for resolve_request in resolve_requests:
                    # Pex / Pip already considered `--pre` / `--no-pre` and the rules laid out in
                    # https://peps.python.org/pep-0440/#handling-of-pre-releases during the lock
                    # resolve; so we trust that resolve's conclusion about prereleases and are
                    # permissive here.
                    if not resolve_request.requirement.contains(
                        locked_requirement.pin.version, prereleases=True
                    ):
                        version_mismatches.append(
                            "{specifier} ({via})".format(
                                specifier=resolve_request.requirement.specifier,
                                via=resolve_request.render_via(),
                            )
                        )
                constraint = constraints_by_project_name.get(locked_requirement.pin.project_name)
                if (
                    constraint is not None
                    and str(locked_requirement.pin.version) not in constraint.specifier
                ):
                    version_mismatches.append(
                        "{specifier} (via: constraint)".format(specifier=constraint.specifier)
                    )
                if version_mismatches:
                    reasons.append(
                        "{pin} does not satisfy the following requirements:\n{mismatches}".format(
                            pin=locked_requirement.pin,
                            mismatches="\n".join(
                                "    {version_mismatch}".format(version_mismatch=version_mismatch)
                                for version_mismatch in version_mismatches
                            ),
                        )
                    )
                    continue

                ranked_artifacts = tuple(
                    locked_requirement.iter_compatible_artifacts(
                        target,
                        build=build_configuration.allow_build(project_name),
                        use_wheel=build_configuration.allow_wheel(project_name),
                    )
                )
                if not ranked_artifacts:
                    reasons.append(
                        attributed_reason(
                            "does not have any compatible artifacts:\n{artifacts}".format(
                                artifacts="\n".join(
                                    "    {url}".format(url=artifact.url.download_url)
                                    for artifact in locked_requirement.iter_artifacts()
                                )
                            )
                        )
                    )
                    continue
                compatible_artifacts.extend(
                    _ResolvedArtifact(ranked_artifact, locked_requirement)
                    for ranked_artifact in ranked_artifacts
                )

            if not compatible_artifacts:
                if reasons:
                    errors.append(
                        "Dependency on {project_name} not satisfied, {count} incompatible "
                        "{candidates} found:\n{reasons}".format(
                            project_name=project_name,
                            count=len(reasons),
                            candidates=pluralize(reasons, "candidate"),
                            reasons="\n".join(
                                "{index}.) {reason}".format(index=index, reason=reason)
                                for index, reason in enumerate(reasons, start=1)
                            ),
                        )
                    )
                elif len(resolve_requests) == 1:
                    errors.append(
                        "Dependency on {project_name} ({via}) not satisfied, no candidates "
                        "found.".format(
                            project_name=project_name, via=resolve_requests[0].render_via()
                        )
                    )
                else:
                    errors.append(
                        "Dependency on {project_name} not satisfied, no candidates found:\n"
                        "    requirers:\n"
                        "    {vias}".format(
                            project_name=project_name,
                            vias="\n    ".join(rr.render_via() for rr in resolve_requests),
                        )
                    )
                continue

            compatible_artifacts.sort(
                key=lambda ra: _ResolvedArtifactComparator(
                    ra, prefer_older_binary=build_configuration.prefer_older_binary
                ),
                reverse=True,  # We want the highest rank sorted 1st.
            )
            if include_all_matches:
                resolved_artifacts.extend(compatible_artifacts)
            else:
                resolved_artifacts.append(compatible_artifacts[0])

        if errors:
            lines = [
                "Failed to resolve all requirements for {target}{from_source}:".format(
                    target=target.render_description(),
                    from_source=" from {source}".format(source=source) if source else "",
                ),
                "",
                "Configured with:",
            ]
            lines.append("    build: {build}".format(build=build_configuration.allow_builds))
            if build_configuration.only_builds:
                lines.append(
                    "    only_build: {only_build}".format(
                        only_build=", ".join(sorted(map(str, build_configuration.only_builds)))
                    )
                )
            lines.append(
                "    use_wheel: {use_wheel}".format(use_wheel=build_configuration.allow_wheels)
            )
            if build_configuration.only_wheels:
                lines.append(
                    "    only_wheel: {only_wheel}".format(
                        only_wheel=", ".join(sorted(map(str, build_configuration.only_wheels)))
                    )
                )
            for error in errors:
                lines.append("")
                lines.append(error)
            return Error("\n".join(lines))

        uniqued_resolved_artifacts = []  # type: List[_ResolvedArtifact]
        seen = set()
        for resolved_artifact in resolved_artifacts:
            if resolved_artifact.ranked_artifact.artifact not in seen:
                uniqued_resolved_artifacts.append(resolved_artifact)
                seen.add(resolved_artifact.ranked_artifact.artifact)

        return Resolved.create(
            target=target,
            direct_requirements=requirements,
            resolved_artifacts=uniqued_resolved_artifacts,
            source=self,
        )
