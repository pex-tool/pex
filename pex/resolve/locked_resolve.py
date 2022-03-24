# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division

import itertools
import os
from collections import OrderedDict, defaultdict, deque

from pex.common import pluralize
from pex.compatibility import urlparse
from pex.dist_metadata import DistMetadata
from pex.enum import Enum
from pex.fetcher import URLFetcher
from pex.pep_425 import CompatibilityTags, TagRank
from pex.pep_503 import ProjectName
from pex.rank import Rank
from pex.requirements import VCS, VCSScheme, parse_scheme
from pex.resolve.resolved_requirement import Fingerprint, PartialArtifact, Pin, ResolvedRequirement
from pex.result import Error
from pex.sorted_tuple import SortedTuple
from pex.targets import LocalInterpreter, Target
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import (
        IO,
        Any,
        Callable,
        DefaultDict,
        Deque,
        Iterable,
        Iterator,
        List,
        Optional,
        Set,
        Tuple,
        Union,
    )

    import attr  # vendor:skip
    from packaging import tags  # vendor:skip
    from packaging import version as packaging_version  # vendor:skip
    from packaging.specifiers import SpecifierSet  # vendor:skip
    from pkg_resources import Requirement  # vendor:skip
else:
    from pex.third_party import attr
    from pex.third_party.packaging import tags
    from pex.third_party.packaging import version as packaging_version
    from pex.third_party.packaging.specifiers import SpecifierSet
    from pex.third_party.pkg_resources import Requirement


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
    @classmethod
    def from_url(
        cls,
        url,  # type: str
        fingerprint,  # type: Fingerprint
        verified=False,  # type: bool
    ):
        # type: (...) -> Union[FileArtifact, VCSArtifact]
        url_info = urlparse.urlparse(url)
        parsed_scheme = parse_scheme(url_info.scheme)
        if isinstance(parsed_scheme, VCSScheme):
            return VCSArtifact(
                url=url, fingerprint=fingerprint, verified=verified, vcs=parsed_scheme.vcs
            )
        else:
            filename = os.path.basename(url_info.path)
            return FileArtifact(
                url=url, fingerprint=fingerprint, verified=verified, filename=filename
            )

    url = attr.ib()  # type: str
    fingerprint = attr.ib()  # type: Fingerprint
    verified = attr.ib()  # type: bool


@attr.s(frozen=True)
class FileArtifact(Artifact):
    filename = attr.ib()  # type: str

    @property
    def is_source(self):
        # type: () -> bool
        return self.filename.endswith((".sdist", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".zip"))

    def parse_tags(self):
        # type: () -> Iterator[tags.Tag]
        if self.filename.endswith(".whl"):
            for tag in CompatibilityTags.from_wheel(self.filename):
                yield tag


@attr.s(frozen=True)
class VCSArtifact(Artifact):
    vcs = attr.ib()  # type: VCS.Value

    @property
    def is_source(self):
        return True

    def as_unparsed_requirement(self, project_name):
        # type: (ProjectName) -> str
        url_info = urlparse.urlparse(self.url)
        if url_info.fragment:
            fragment_parameters = urlparse.parse_qs(url_info.fragment)
            names = fragment_parameters.get("egg")
            if names and ProjectName(names[-1]) == project_name:
                # A Pip proprietary VCS requirement.
                return self.url
        # A PEP-440 direct reference VCS requirement with the project name stripped from earlier
        # processing. See: https://peps.python.org/pep-0440/#direct-references
        return "{project_name} @ {url}".format(project_name=project_name, url=self.url)


@attr.s(frozen=True)
class RankedArtifact(object):
    artifact = attr.ib()  # type: Union[FileArtifact, VCSArtifact]
    rank = attr.ib()  # type: TagRank

    def select_higher_ranked(self, other):
        # type: (RankedArtifact) -> RankedArtifact
        return Rank.select_highest_rank(
            self, other, extract_rank=lambda ranked_artifact: ranked_artifact.rank
        )


@attr.s(frozen=True)
class LockedRequirement(object):
    @classmethod
    def create(
        cls,
        pin,  # type: Pin
        artifact,  # type: Union[FileArtifact, VCSArtifact]
        requires_dists=(),  # type: Iterable[Requirement]
        requires_python=None,  # type: Optional[SpecifierSet]
        additional_artifacts=(),  # type: Iterable[Union[FileArtifact, VCSArtifact]]
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
    artifact = attr.ib()  # type: Union[FileArtifact, VCSArtifact]
    requires_dists = attr.ib(default=SortedTuple())  # type: SortedTuple[Requirement]
    requires_python = attr.ib(default=None)  # type: Optional[SpecifierSet]
    additional_artifacts = attr.ib(
        default=SortedTuple()
    )  # type: SortedTuple[Union[FileArtifact, VCSArtifact]]

    def iter_artifacts(self):
        # type: () -> Iterator[Union[FileArtifact, VCSArtifact]]
        yield self.artifact
        for artifact in self.additional_artifacts:
            yield artifact

    def select_artifact(
        self,
        target,  # type: Target
        build=True,  # type: bool
        use_wheel=True,  # type: bool
    ):
        # type: (...) -> Optional[RankedArtifact]
        """Select the highest ranking (most platform specific) artifact satisfying supported tags.

        Artifacts are ranked as follows:

        + If the artifact is a wheel, rank it based on its best matching tag.
        + If the artifact is an sdist, rank it as usable, but a worse match than any wheel.
        + Otherwise treat the artifact as unusable.

        :param target: The target looking to pick a resolve to use.
        :param build: Whether sdists are allowed.
        :param use_wheel: Whether wheels are allowed.
        :return: The highest ranked artifact if the requirement is compatible with the target else
            `None`.
        """
        highest_rank_artifact = None  # type: Optional[RankedArtifact]
        for artifact in self.iter_artifacts():
            if build and artifact.is_source:
                # N.B.: Ensure sdists are picked last amongst a set of artifacts. We do this, since
                # a wheel is known to work with a target by the platform tags on the tin, whereas an
                # sdist may not successfully build for a given target at all. This is an affordance
                # for LockStyle.SOURCES and LockStyle.CROSS_PLATFORM lock styles.
                sdist_rank = target.supported_tags.lowest_rank.lower()
                ranked_artifact = RankedArtifact(artifact=artifact, rank=sdist_rank)
                if (
                    highest_rank_artifact is None
                    or ranked_artifact
                    is highest_rank_artifact.select_higher_ranked(ranked_artifact)
                ):
                    highest_rank_artifact = ranked_artifact
            elif use_wheel and isinstance(artifact, FileArtifact):
                for tag in artifact.parse_tags():
                    wheel_rank = target.supported_tags.rank(tag)
                    if wheel_rank is None:
                        continue
                    ranked_artifact = RankedArtifact(artifact=artifact, rank=wheel_rank)
                    if (
                        highest_rank_artifact is None
                        or ranked_artifact
                        is highest_rank_artifact.select_higher_ranked(ranked_artifact)
                    ):
                        highest_rank_artifact = ranked_artifact

        return highest_rank_artifact


@attr.s(frozen=True)
class _ResolveRequest(object):
    @classmethod
    def root(cls, requirement):
        # type: (Requirement) -> _ResolveRequest
        return cls(required_by=(requirement,), requirement=requirement)

    required_by = attr.ib()  # type: Tuple[Requirement, ...]
    requirement = attr.ib()  # type: Requirement
    extras = attr.ib(default=None)  # type: Optional[Tuple[str, ...]]

    @property
    def project_name(self):
        # type: () -> ProjectName
        return ProjectName(self.requirement.project_name)

    def request_dependencies(self, locked_requirement):
        # type: (LockedRequirement) -> Iterator[_ResolveRequest]
        for requires_dist in locked_requirement.requires_dists:
            yield _ResolveRequest(
                required_by=self.required_by + (requires_dist,),
                requirement=requires_dist,
                extras=self.requirement.extras,
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
        # type: () -> Union[FileArtifact, VCSArtifact]
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


@attr.s(frozen=True)
class DownloadableArtifact(object):
    @classmethod
    def create(
        cls,
        pin,  # type: Pin
        artifact,  # type: Union[FileArtifact, VCSArtifact]
        satisfied_direct_requirements=(),  # type: Iterable[Requirement]
    ):
        # type: (...) -> DownloadableArtifact
        return cls(
            pin=pin,
            artifact=artifact,
            satisfied_direct_requirements=SortedTuple(satisfied_direct_requirements, key=str),
        )

    pin = attr.ib()  # type: Pin
    artifact = attr.ib()  # type: Union[FileArtifact, VCSArtifact]
    satisfied_direct_requirements = attr.ib(default=SortedTuple())  # type: SortedTuple[Requirement]


@attr.s(frozen=True)
class Resolved(object):
    @classmethod
    def create(
        cls,
        target,  # type: Target
        direct_requirements,  # type: Iterable[Requirement]
        downloadable_requirements,  # type: Iterable[_ResolvedArtifact]
    ):
        # type: (...) -> Resolved

        direct_requirements_by_project_name = defaultdict(
            list
        )  # type: DefaultDict[ProjectName, List[Requirement]]
        for requirement in direct_requirements:
            direct_requirements_by_project_name[ProjectName(requirement.project_name)].append(
                requirement
            )

        # N.B.: Lowest rank means highest rank value. I.E.: The 1st tag is the most specific and
        # the 765th tag is the least specific.
        largest_rank_value = target.supported_tags.lowest_rank.value
        smallest_rank_value = TagRank.highest_natural().value
        rank_span = largest_rank_value - smallest_rank_value

        downloadable_artifacts = []
        target_specificities = []
        for downloadable_requirement in downloadable_requirements:
            pin = downloadable_requirement.locked_requirement.pin
            downloadable_artifacts.append(
                DownloadableArtifact.create(
                    pin=pin,
                    artifact=downloadable_requirement.artifact,
                    satisfied_direct_requirements=direct_requirements_by_project_name[
                        pin.project_name
                    ],
                )
            )
            target_specificities.append(
                (
                    rank_span
                    - (downloadable_requirement.ranked_artifact.rank.value - smallest_rank_value)
                )
                / rank_span
            )

        return cls(
            target_specificity=sum(target_specificities) / len(target_specificities),
            downloadable_artifacts=tuple(downloadable_artifacts),
        )

    target_specificity = attr.ib()  # type: float
    downloadable_artifacts = attr.ib()  # type: Tuple[DownloadableArtifact, ...]


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
                    resolved_requirement.iter_urls_to_fingerprint()
                    for resolved_requirement in resolved_requirements
                )
            )
        }

        def resolve_fingerprint(partial_artifact):
            # type: (PartialArtifact) -> Union[FileArtifact, VCSArtifact]
            url = partial_artifact.url
            if partial_artifact.fingerprint:
                return Artifact.from_url(
                    url=url,
                    fingerprint=partial_artifact.fingerprint,
                    verified=partial_artifact.verified,
                )
            return Artifact.from_url(url=url, fingerprint=fingerprint_by_url[url], verified=True)

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
            artifact,  # type: Union[FileArtifact, VCSArtifact]
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

    def resolve(
        self,
        target,  # type: Target
        requirements,  # type: Iterable[Requirement]
        constraints=(),  # type: Iterable[Requirement]
        source=None,  # type: Optional[str]
        transitive=True,  # type: bool
        build=True,  # type: bool
        use_wheel=True,  # type: bool
        prefer_older_binary=False,  # type: bool
    ):
        # type: (...) -> Union[Resolved, Error]

        is_local_interpreter = isinstance(target, LocalInterpreter)
        if not use_wheel:
            if not build:
                return Error(
                    "Cannot both ignore wheels (use_wheel=False) and refrain from building "
                    "distributions (build=False)."
                )
            elif not is_local_interpreter:
                return Error(
                    "Cannot ignore wheels (use_wheel=False) when resolving for a platform: given "
                    "{platform_description}".format(
                        platform_description=target.render_description()
                    )
                )
        if not is_local_interpreter:
            build = False

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
                if target.requirement_applies(request.requirement, extras=request.extras)
            )

        visited = set()  # type: Set[ProjectName]
        request_resolve(_ResolveRequest.root(requirement) for requirement in requirements)
        while to_be_resolved:
            resolve_request = to_be_resolved.popleft()
            project_name = resolve_request.project_name
            required.setdefault(project_name, []).append(resolve_request)

            if not transitive or project_name in visited:
                continue
            visited.add(project_name)

            for locked_requirement in repository[project_name]:
                request_resolve(resolve_request.request_dependencies(locked_requirement))

        # 2. Select either the best fit artifact for each requirement or collect an error.
        constraints_by_project_name = {
            ProjectName(constraint.project_name): constraint for constraint in constraints
        }
        resolved_artifacts = []
        errors = []
        for project_name, resolve_requests in required.items():
            reasons = []  # type: List[str]
            best_match = None  # type: Optional[_ResolvedArtifact]
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
                    if (
                        str(locked_requirement.pin.version)
                        not in resolve_request.requirement.specifier
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

                ranked_artifact = locked_requirement.select_artifact(
                    target,
                    build=build,
                    use_wheel=use_wheel,
                )
                if not ranked_artifact:
                    reasons.append(
                        attributed_reason(
                            "does not have any compatible artifacts:\n{artifacts}".format(
                                artifacts="\n".join(
                                    "    {url}".format(url=artifact.url)
                                    for artifact in locked_requirement.iter_artifacts()
                                )
                            )
                        )
                    )
                    continue
                resolved_artifact = _ResolvedArtifact(ranked_artifact, locked_requirement)
                if best_match is None or resolved_artifact is best_match.select_higher_rank(
                    resolved_artifact, prefer_older_binary=prefer_older_binary
                ):
                    best_match = resolved_artifact

            if not best_match:
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

            resolved_artifacts.append(best_match)

        if errors:
            from_source = " from {source}".format(source=source) if source else ""
            return Error(
                "Failed to resolve all requirements for {target}{from_source}:\n"
                "\n"
                "Configured with:\n"
                "    build: {build}\n"
                "    use_wheel: {use_wheel}\n"
                "\n"
                "{errors}".format(
                    target=target.render_description(),
                    from_source=from_source,
                    build=build,
                    use_wheel=use_wheel,
                    errors="\n\n".join("{error}".format(error=error) for error in errors),
                )
            )

        return Resolved.create(
            target=target,
            direct_requirements=requirements,
            downloadable_requirements=resolved_artifacts,
        )
