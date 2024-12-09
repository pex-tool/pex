# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import logging
import os
from collections import OrderedDict
from contextlib import contextmanager

from pex.common import pluralize
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import Constraint, Requirement
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.requirements import PyPIRequirement, URLRequirement, VCSRequirement
from pex.resolve.locked_resolve import (
    Artifact,
    FileArtifact,
    LockConfiguration,
    LockedRequirement,
    LockedResolve,
)
from pex.resolve.lockfile.create import create
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolved_requirement import ArtifactURL, Fingerprint
from pex.resolve.resolver_configuration import PipConfiguration, PipLog, ReposConfiguration
from pex.result import Error, ResultError, catch, try_
from pex.sorted_tuple import SortedTuple
from pex.targets import Target, Targets
from pex.third_party.packaging import tags
from pex.typing import TYPE_CHECKING
from pex.util import named_temporary_file

if TYPE_CHECKING:
    from typing import (
        Any,
        Container,
        Dict,
        Iterable,
        Iterator,
        List,
        Mapping,
        Optional,
        Tuple,
        Union,
    )

    import attr  # vendor:skip

    from pex.requirements import ParsedRequirement
else:
    from pex.third_party import attr


logger = logging.getLogger(__name__)


@attr.s(frozen=True)
class DeleteUpdate(object):
    version = attr.ib()  # type: Version


@attr.s(frozen=True)
class VersionUpdate(object):
    original = attr.ib()  # type: Optional[Version]
    updated = attr.ib()  # type: Version


@attr.s(frozen=True)
class URLUpdate(object):
    original = attr.ib()  # type: ArtifactURL
    updated = attr.ib()  # type: ArtifactURL

    def render_update(self):
        # type: () -> str
        return "{original} -> {updated}".format(
            original=self.original.download_url, updated=self.updated.download_url
        )


@attr.s(frozen=True)
class FingerprintUpdate(object):
    source = attr.ib()  # type: str
    original = attr.ib()  # type: Fingerprint
    updated = attr.ib()  # type: Fingerprint

    def render_update(self):
        # type: () -> str
        return "{source} {o_alg}:{o_hash} -> {u_alg}:{u_hash}".format(
            source=self.source,
            o_alg=self.original.algorithm,
            o_hash=self.original.hash,
            u_alg=self.updated.algorithm,
            u_hash=self.updated.hash,
        )


@attr.s(frozen=True)
class ArtifactUpdate(object):
    original = attr.ib()  # type: Artifact
    updated = attr.ib()  # type: Artifact

    def render_update(self):
        # type: () -> str
        return "{o_url}#{o_alg}:{o_hash} -> {u_url}#{u_alg}:{u_hash}".format(
            o_url=self.original.url.download_url,
            o_alg=self.original.fingerprint.algorithm,
            o_hash=self.original.fingerprint.hash,
            u_url=self.updated.url.download_url,
            u_alg=self.updated.fingerprint.algorithm,
            u_hash=self.updated.fingerprint.hash,
        )


@attr.s(frozen=True)
class ArtifactsUpdate(object):
    @classmethod
    def calculate(
        cls,
        version,  # type: Version
        original,  # type: Tuple[Artifact, ...]
        updated,  # type: Tuple[Artifact, ...]
    ):
        # type: (...) -> ArtifactsUpdate

        def key(artifact):
            # type: (Artifact) -> str
            return (
                artifact.filename
                if isinstance(artifact, FileArtifact)
                else artifact.url.normalized_url
            )

        def calculate_updates(
            original_art,  # type: Artifact
            updated_art,  # type: Artifact
        ):
            # type: (...) -> Iterator[Union[URLUpdate, FingerprintUpdate, ArtifactUpdate]]

            # N.B.: We don't care if fingerprints have been verified or not, we just care if the
            # advertised value has changed. That could indicate the original advertised value was
            # bad and is now corrected, but if that's the case the user can choose to ignore the
            # potentially dangerous update if they know for a fact from out of band investigation
            # that the new fingerprint is the correct one.
            if attr.evolve(original_art, verified=False) == attr.evolve(
                updated_art, verified=False
            ):
                return

            if original_art.fingerprint == updated_art.fingerprint:
                yield URLUpdate(original=original_art.url, updated=updated_art.url)
            elif original_art.url == updated_art.url:
                yield FingerprintUpdate(
                    source=key(original_art),
                    original=original_art.fingerprint,
                    updated=updated_art.fingerprint,
                )
            else:
                yield ArtifactUpdate(original=original_art, updated=updated_art)

        original_artifacts = {key(artifact): artifact for artifact in original}
        added_artifacts = []  # type: List[Artifact]
        updated_artifacts = []  # type: List[Union[URLUpdate, FingerprintUpdate, ArtifactUpdate]]
        for updated_artifact in updated:
            original_artifact = original_artifacts.pop(key(updated_artifact), None)
            if not original_artifact:
                added_artifacts.append(updated_artifact)
            else:
                updated_artifacts.extend(
                    calculate_updates(original_art=original_artifact, updated_art=updated_artifact)
                )
        removed_artifacts = tuple(original_artifacts.values())

        return cls(
            version=version,
            added=tuple(added_artifacts),
            updated=tuple(updated_artifacts),
            removed=tuple(removed_artifacts),
        )

    version = attr.ib()  # type: Version
    added = attr.ib()  # type: Tuple[Artifact, ...]
    updated = attr.ib()  # type: Tuple[Union[URLUpdate, FingerprintUpdate, ArtifactUpdate], ...]
    removed = attr.ib()  # type: Tuple[Artifact, ...]


@attr.s(frozen=True)
class RequirementsUpdate(object):
    @classmethod
    def calculate(
        cls,
        version,  # type: Version
        original,  # type: Tuple[Requirement, ...]
        updated,  # type: Tuple[Requirement, ...]
    ):
        # type: (...) -> RequirementsUpdate
        added = []  # type: List[Requirement]
        removed = []  # type: List[Requirement]
        for req in updated:
            if req not in original:
                added.append(req)
        for req in original:
            if req not in updated:
                removed.append(req)
        return cls(version=version, added=tuple(added), removed=tuple(removed))

    version = attr.ib()  # type: Version
    added = attr.ib()  # type: Tuple[Requirement, ...]
    removed = attr.ib()  # type: Tuple[Requirement, ...]


if TYPE_CHECKING:
    Update = Union[DeleteUpdate, VersionUpdate, ArtifactsUpdate, RequirementsUpdate]


@attr.s(frozen=True)
class ResolveUpdate(object):
    updated_resolve = attr.ib()  # type: LockedResolve
    updates = attr.ib(factory=dict)  # type: Mapping[ProjectName, Optional[Update]]


@attr.s(frozen=True)
class ResolveUpdater(object):
    """Updates a resolve in whole or in part.

    A resolve updater with no updates specified just updates the whole locked resolve with the
    latest available distributions that satisfy the locked resolve criteria.

    More interestingly, a resolve updater with a set of updates will attempt to alter just the
    distributions for those updates. The update can be just a plain project name in which case the
    latest compatible distribution for that project will be used. The update can also be a
    full-fledged constraint with a specifier, in which case a distribution matching the constraint
    and still satisfying the rest of the locked resolve will be searched for. This facility allows
    for targeted upgrades and downgrades of individual projects in a lock that maintain the
    integrity of the locked resolve.

    When a set of updates is specified, the updater ensures all other project distributions remain
    unchanged.
    """

    @classmethod
    def derived(
        cls,
        requirement_configuration,  # type: RequirementConfiguration
        parsed_requirements,  # type: Iterable[ParsedRequirement]
        lock_file,  # type: Lockfile
        lock_configuration,  # type: LockConfiguration
        pip_configuration,  # type: PipConfiguration
        dependency_configuration,  # type: DependencyConfiguration
    ):
        # type: (...) -> Union[ResolveUpdater, Error]

        original_requirements_by_project_name = OrderedDict(
            (requirement.project_name, requirement) for requirement in lock_file.requirements
        )  # type: OrderedDict[ProjectName, Requirement]

        replace_requirements = []  # type: List[Requirement]
        for parsed_requirement in parsed_requirements:
            if isinstance(parsed_requirement, (PyPIRequirement, URLRequirement, VCSRequirement)):
                requirement = parsed_requirement.requirement
                original_requirement = original_requirements_by_project_name.pop(
                    requirement.project_name, None
                )
                if requirement != original_requirement:
                    replace_requirements.append(requirement)
            else:
                return Error(
                    "Cannot update a bare local project directory requirement on {path}.\n"
                    "Try re-phrasing as a PEP-508 direct reference with a file:// URL.\n"
                    "See: https://peps.python.org/pep-0508/".format(path=parsed_requirement.path)
                )

        deletes = tuple(original_requirements_by_project_name) if parsed_requirements else ()

        original_constraints_by_project_name = OrderedDict(
            (constraint.project_name, constraint) for constraint in lock_file.constraints
        )  # type: OrderedDict[ProjectName, Constraint]

        update_constraints_by_project_name = (
            OrderedDict()
        )  # type: OrderedDict[ProjectName, Constraint]
        for requirement in replace_requirements:
            project_name = requirement.project_name
            original_constraint = original_constraints_by_project_name.get(project_name)
            if original_constraint:
                logger.warning(
                    "Over-riding original constraint {original} with {override}.".format(
                        original=original_constraint, override=requirement
                    )
                )
            update_constraints_by_project_name[project_name] = requirement.as_constraint()

        original_requirements = OrderedDict(
            (requirement.project_name, requirement) for requirement in lock_file.requirements
        )  # type: OrderedDict[ProjectName, Requirement]
        original_requirements.update(
            (replacement.project_name, replacement) for replacement in replace_requirements
        )
        return cls(
            requirement_configuration=requirement_configuration,
            original_requirements=tuple(original_requirements.values()),
            update_constraints_by_project_name=update_constraints_by_project_name,
            deletes=frozenset(deletes),
            pure_delete=bool(deletes and not replace_requirements),
            lock_configuration=lock_configuration,
            pip_configuration=pip_configuration,
            dependency_configuration=dependency_configuration,
        )

    @classmethod
    def specified(
        cls,
        updates,  # type: Iterable[Requirement]
        replacements,  # type: Iterable[Requirement]
        deletes,  # type: Iterable[ProjectName]
        lock_file,  # type: Lockfile
        lock_configuration,  # type: LockConfiguration
        pip_configuration,  # type: PipConfiguration
        dependency_configuration,  # type: DependencyConfiguration
    ):
        # type: (...) -> ResolveUpdater

        original_requirements_by_project_name = OrderedDict(
            (requirement.project_name, requirement) for requirement in lock_file.requirements
        )  # type: OrderedDict[ProjectName, Requirement]
        original_requirements_by_project_name.update(
            (replacement.project_name, replacement) for replacement in replacements
        )

        original_constraints_by_project_name = OrderedDict(
            (constraint.project_name, constraint) for constraint in lock_file.constraints
        )  # type: OrderedDict[ProjectName, Constraint]

        update_constraints_by_project_name = (
            OrderedDict()
        )  # type: OrderedDict[ProjectName, Constraint]
        for change in itertools.chain(updates, replacements):
            project_name = change.project_name
            original_constraint = original_constraints_by_project_name.get(project_name)
            if original_constraint:
                logger.warning(
                    "Over-riding original constraint {original} with {override}.".format(
                        original=original_constraint, override=change
                    )
                )
            update_constraints_by_project_name[project_name] = change.as_constraint()

        return cls(
            requirement_configuration=RequirementConfiguration(
                requirements=[str(req) for req in original_requirements_by_project_name.values()],
            ),
            original_requirements=tuple(original_requirements_by_project_name.values()),
            update_requirements_by_project_name={update.project_name: update for update in updates},
            update_constraints_by_project_name=update_constraints_by_project_name,
            deletes=frozenset(deletes),
            pure_delete=bool(deletes and not updates and not replacements),
            lock_configuration=lock_configuration,
            pip_configuration=pip_configuration,
            dependency_configuration=dependency_configuration,
        )

    requirement_configuration = attr.ib()  # type: RequirementConfiguration
    original_requirements = attr.ib()  # type: Iterable[Requirement]
    update_constraints_by_project_name = attr.ib()  # type: Mapping[ProjectName, Constraint]
    deletes = attr.ib()  # type: Container[ProjectName]
    pure_delete = attr.ib()  # type: bool
    lock_configuration = attr.ib()  # type: LockConfiguration
    pip_configuration = attr.ib()  # type: PipConfiguration
    dependency_configuration = attr.ib(
        default=DependencyConfiguration()
    )  # type: DependencyConfiguration
    update_requirements_by_project_name = attr.ib(
        factory=dict
    )  # type: Mapping[ProjectName, Requirement]

    def iter_updated_requirements(self):
        # type: () -> Iterator[Requirement]
        for requirement in self.original_requirements:
            if requirement.project_name not in self.deletes:
                yield requirement

    @contextmanager
    def _calculate_requirement_configuration(
        self,
        locked_resolve,  # type: LockedResolve
        artifacts_can_change=False,  # type: bool
    ):
        # type: (...) -> Iterator[Optional[RequirementConfiguration]]
        if not self.update_constraints_by_project_name and not artifacts_can_change:
            yield None
            return

        requirements = OrderedSet(map(str, self.original_requirements))
        constraints = []
        update_constraints_by_project_name = OrderedDict(self.update_constraints_by_project_name)
        for locked_requirement in locked_resolve.locked_requirements:
            pin = locked_requirement.pin
            pinned_requirement = pin.as_requirement()

            # Don't constrain an already locked requirement that has an incompatible override
            # (which implies a new `--override`); i.e: let the override freely resolve.
            if any(
                pinned_requirement not in override
                for override in self.dependency_configuration.overrides_for(pinned_requirement)
            ):
                continue

            constraint = update_constraints_by_project_name.pop(
                pin.project_name, pinned_requirement
            )
            constraints.append(str(constraint))

        # Any update constraints remaining are new requirements to resolve.
        requirements.update(str(req) for req in update_constraints_by_project_name.values())

        if not constraints:
            yield attr.evolve(self.requirement_configuration, requirements=requirements)
            return

        with named_temporary_file(prefix="lock_update.", suffix=".constraints.txt", mode="w") as fp:
            fp.write(os.linesep.join(constraints))
            fp.flush()
            constraint_files = [fp.name]
            if self.requirement_configuration.constraint_files:
                constraint_files.extend(self.requirement_configuration.constraint_files)
            try:
                yield attr.evolve(
                    self.requirement_configuration,
                    requirements=requirements,
                    constraint_files=constraint_files,
                )
            except ResultError as e:
                logger.error(
                    "Given the lock requirements:\n"
                    "{requirements}\n"
                    "\n"
                    "The following lock update constraints could not all be satisfied:\n"
                    "{constraints}\n".format(
                        requirements="\n".join(requirements), constraints="\n".join(constraints)
                    )
                )
                raise e

    def _pure_delete(self, locked_resolve):
        # type: (LockedResolve) -> LockedResolve

        to_delete = {
            locked_requirement.pin.project_name: locked_requirement
            for locked_requirement in locked_resolve.locked_requirements
        }

        def remove_requirements_to_be_retained(
            reqs,  # type: Iterable[Requirement]
        ):
            # type: (...) -> None
            for req in reqs:
                if req.project_name in self.deletes:
                    continue
                locked_requirement_to_retain = to_delete.pop(req.project_name, None)
                if not locked_requirement_to_retain:
                    # We've already visited this node via another dependency chain
                    continue
                remove_requirements_to_be_retained(locked_requirement_to_retain.requires_dists)

        remove_requirements_to_be_retained(self.original_requirements)

        return attr.evolve(
            locked_resolve,
            locked_requirements=SortedTuple(
                locked_requirement
                for locked_requirement in locked_resolve.locked_requirements
                if locked_requirement.pin.project_name not in to_delete
            ),
        )

    def update_resolve(
        self,
        locked_resolve,  # type: LockedResolve
        target,  # type: Target
        artifacts_can_change=False,  # type: bool
    ):
        # type: (...) -> Union[ResolveUpdate, Error]

        updated_resolve = locked_resolve
        updated_requirements = self.original_requirements
        with self._calculate_requirement_configuration(
            locked_resolve, artifacts_can_change=artifacts_can_change
        ) as requirement_configuration:
            if requirement_configuration:
                if self.pure_delete:
                    updated_resolve = self._pure_delete(locked_resolve)
                else:
                    updated_lock_file = try_(
                        create(
                            lock_configuration=self.lock_configuration,
                            requirement_configuration=requirement_configuration,
                            targets=Targets.from_target(target),
                            pip_configuration=self.pip_configuration,
                            dependency_configuration=self.dependency_configuration,
                        )
                    )
                    assert 1 == len(updated_lock_file.locked_resolves)
                    updated_resolve = updated_lock_file.locked_resolves[0]
                    updated_requirements = updated_lock_file.requirements

        updates = OrderedDict()  # type: OrderedDict[ProjectName, Optional[Update]]

        if self.deletes or self.dependency_configuration.excluded:
            reduced_requirements = [
                requirement
                for requirement in updated_requirements
                if (
                    requirement.project_name not in self.deletes
                    and not self.dependency_configuration.excluded_by(requirement)
                )
            ]
            resolve = try_(
                updated_resolve.resolve(
                    target=target,
                    requirements=reduced_requirements,
                    dependency_configuration=self.dependency_configuration,
                )
            )
            included_projects = frozenset(
                artifact.pin.project_name for artifact in resolve.downloadable_artifacts
            )
            updates.update(
                (locked_requirement.pin.project_name, DeleteUpdate(locked_requirement.pin.version))
                for locked_requirement in locked_resolve.locked_requirements
                if locked_requirement.pin.project_name not in included_projects
            )
            updated_resolve = attr.evolve(
                updated_resolve,
                locked_requirements=SortedTuple(
                    [
                        locked_requirement
                        for locked_requirement in updated_resolve.locked_requirements
                        if locked_requirement.pin.project_name in included_projects
                    ]
                ),
            )

        updated_requirements_by_project_name = OrderedDict(
            (updated_requirement.pin.project_name, updated_requirement)
            for updated_requirement in updated_resolve.locked_requirements
        )  # type: OrderedDict[ProjectName, LockedRequirement]
        for locked_requirement in locked_resolve.locked_requirements:
            original_pin = locked_requirement.pin
            project_name = original_pin.project_name
            updated_requirement = updated_requirements_by_project_name.pop(project_name, None)
            if not updated_requirement:
                continue
            updated_pin = updated_requirement.pin
            original_artifacts = tuple(locked_requirement.iter_artifacts())
            updated_artifacts = tuple(updated_requirement.iter_artifacts())
            original_requirements = locked_requirement.requires_dists
            updated_requirements = updated_requirement.requires_dists

            # N.B.: We use a custom key for artifact equality comparison since `Artifact`
            # contains a `verified` attribute that can both vary based on Pex's current
            # knowledge about the trustworthiness of an artifact hash and is not relevant to
            # whether the artifact refers to the same artifact.
            def artifact_key(artifact):
                # type: (Artifact) -> Any
                return artifact.url, artifact.fingerprint

            def artifacts_differ():
                # type: () -> bool
                return tuple(map(artifact_key, original_artifacts)) != tuple(
                    map(artifact_key, updated_artifacts)
                )

            if (
                self.update_constraints_by_project_name
                and project_name not in self.update_constraints_by_project_name
            ):
                assert updated_pin == original_pin, (
                    "The locked requirement {original} should have been undisturbed by the lock "
                    "update, but it changed to {updated}.".format(
                        original=original_pin.as_requirement(), updated=updated_pin.as_requirement()
                    )
                )

                if artifacts_can_change and artifacts_differ():
                    updates[project_name] = ArtifactsUpdate.calculate(
                        version=original_pin.version,
                        original=original_artifacts,
                        updated=updated_artifacts,
                    )
                    continue

                assert artifact_key(updated_requirement.artifact) == artifact_key(
                    locked_requirement.artifact
                ), (
                    "The locked requirement {original} should have been undisturbed by the lock "
                    "update, but its primary artifact changed from:\n"
                    "{original_artifact}\n"
                    "to:\n"
                    "{updated_artifact}".format(
                        original=original_pin.as_requirement(),
                        original_artifact=artifact_key(locked_requirement.artifact),
                        updated_artifact=artifact_key(updated_requirement.artifact),
                    )
                )
                assert set(map(artifact_key, updated_requirement.additional_artifacts)) == set(
                    map(artifact_key, locked_requirement.additional_artifacts)
                ), (
                    "The locked requirement {original} should have been undisturbed by the lock "
                    "update, but its additional artifact set changed from:\n"
                    "{original_artifacts}\n"
                    "to:\n"
                    "{updated_artifacts}".format(
                        original=original_pin.as_requirement(),
                        original_artifacts="\n".join(
                            map(
                                lambda a: str(artifact_key(a)),
                                locked_requirement.additional_artifacts,
                            )
                        ),
                        updated_artifacts="\n".join(
                            map(
                                lambda a: str(artifact_key(a)),
                                updated_requirement.additional_artifacts,
                            )
                        ),
                    )
                )
            elif original_pin != updated_pin:
                updates[project_name] = VersionUpdate(
                    original=original_pin.version, updated=updated_pin.version
                )
            elif artifacts_differ():
                updates[project_name] = ArtifactsUpdate.calculate(
                    version=original_pin.version,
                    original=original_artifacts,
                    updated=updated_artifacts,
                )
            elif original_requirements != updated_requirements:
                updates[project_name] = RequirementsUpdate.calculate(
                    version=original_pin.version,
                    original=original_requirements,
                    updated=updated_requirements,
                )
            elif project_name in self.update_constraints_by_project_name:
                updates[project_name] = None

        # Anything left was an addition.
        updates.update(
            (project_name, VersionUpdate(original=None, updated=locked_requirement.pin.version))
            for project_name, locked_requirement in updated_requirements_by_project_name.items()
        )

        return ResolveUpdate(
            updated_resolve=attr.evolve(
                locked_resolve,
                locked_requirements=SortedTuple(updated_resolve.locked_requirements),
            ),
            updates=updates,
        )


@attr.s(frozen=True)
class ResolveUpdateRequest(object):
    target = attr.ib()  # type: Target
    locked_resolve = attr.ib()  # type: LockedResolve


@attr.s(frozen=True)
class LockUpdate(object):
    requirements = attr.ib()  # type: Iterable[Requirement]
    resolves = attr.ib()  # type: Iterable[ResolveUpdate]
    update_requirements_by_project_name = attr.ib(
        factory=dict
    )  # type: Mapping[ProjectName, Requirement]


@attr.s(frozen=True)
class LockUpdater(object):
    @classmethod
    def create(
        cls,
        lock_file,  # type: Lockfile
        repos_configuration,  # type: ReposConfiguration
        network_configuration,  # type: NetworkConfiguration
        max_jobs,  # type: int
        use_pip_config,  # type: bool
        dependency_configuration,  # type: DependencyConfiguration
        pip_log,  # type: Optional[PipLog]
    ):
        # type: (...) -> LockUpdater

        pip_configuration = PipConfiguration(
            version=lock_file.pip_version,
            resolver_version=lock_file.resolver_version,
            allow_prereleases=lock_file.allow_prereleases,
            build_configuration=lock_file.build_configuration(),
            transitive=lock_file.transitive,
            repos_configuration=repos_configuration,
            network_configuration=network_configuration,
            max_jobs=max_jobs,
            use_pip_config=use_pip_config,
            log=pip_log,
        )
        return cls(
            lock_file=lock_file,
            lock_configuration=lock_file.lock_configuration(),
            pip_configuration=pip_configuration,
            dependency_configuration=dependency_configuration,
        )

    lock_file = attr.ib()  # type: Lockfile
    lock_configuration = attr.ib()  # type: LockConfiguration
    pip_configuration = attr.ib()  # type: PipConfiguration
    dependency_configuration = attr.ib()  # type: DependencyConfiguration

    def sync(
        self,
        update_requests,  # type: Iterable[ResolveUpdateRequest]
        requirement_configuration,  # type: RequirementConfiguration
    ):
        # type: (...) -> Union[LockUpdate, Error]

        requirements = tuple(
            requirement_configuration.parse_requirements(
                self.pip_configuration.network_configuration
            )
        )
        resolve_updater = try_(
            ResolveUpdater.derived(
                requirement_configuration=requirement_configuration,
                parsed_requirements=requirements,
                lock_file=self.lock_file,
                lock_configuration=self.lock_configuration,
                pip_configuration=self.pip_configuration,
                dependency_configuration=self.dependency_configuration,
            )
        )
        return self._perform_update(
            update_requests=update_requests,
            resolve_updater=resolve_updater,
            artifacts_can_change=True,
        )

    def update(
        self,
        update_requests,  # type: Iterable[ResolveUpdateRequest]
        updates=(),  # type: Iterable[Requirement]
        replacements=(),  # type: Iterable[Requirement]
        deletes=(),  # type: Iterable[ProjectName]
        artifacts_can_change=False,  # type: bool
    ):
        # type: (...) -> Union[LockUpdate, Error]

        if not any((artifacts_can_change, updates, replacements, deletes)):
            return LockUpdate(
                requirements=self.lock_file.requirements,
                resolves=tuple(
                    ResolveUpdate(updated_resolve=update_request.locked_resolve)
                    for update_request in update_requests
                ),
            )

        resolve_updater = ResolveUpdater.specified(
            updates=updates,
            replacements=replacements,
            deletes=deletes,
            lock_file=self.lock_file,
            lock_configuration=self.lock_configuration,
            pip_configuration=self.pip_configuration,
            dependency_configuration=self.dependency_configuration,
        )
        return self._perform_update(
            update_requests=update_requests,
            resolve_updater=resolve_updater,
            artifacts_can_change=artifacts_can_change,
        )

    def _perform_update(
        self,
        update_requests,  # type: Iterable[ResolveUpdateRequest]
        resolve_updater,  # type: ResolveUpdater
        artifacts_can_change=False,  # type: bool
    ):
        # type: (...) -> Union[LockUpdate, Error]

        error_by_target = OrderedDict()  # type: OrderedDict[Target, Error]
        locked_resolve_by_platform_tag = OrderedDict(
            (locked_resolve.platform_tag, locked_resolve)
            for locked_resolve in self.lock_file.locked_resolves
        )  # type: OrderedDict[Optional[tags.Tag], LockedResolve]
        resolve_updates_by_platform_tag = (
            {}
        )  # type: Dict[Optional[tags.Tag], Mapping[ProjectName, Optional[Update]]]

        # TODO(John Sirois): Consider parallelizing this. The underlying Jobs are down a few layers;
        #  so this will likely require using multiprocessing.
        for update_request in update_requests:
            result = catch(
                resolve_updater.update_resolve,
                locked_resolve=update_request.locked_resolve,
                target=update_request.target,
                artifacts_can_change=artifacts_can_change,
            )
            if isinstance(result, Error):
                error_by_target[update_request.target] = result
            else:
                platform_tag = update_request.locked_resolve.platform_tag
                locked_resolve_by_platform_tag[platform_tag] = result.updated_resolve
                resolve_updates_by_platform_tag[platform_tag] = result.updates

        if error_by_target:
            return Error(
                "Encountered {count} {errors} updating {lockfile_path}:\n{error_details}".format(
                    count=len(error_by_target),
                    errors=pluralize(error_by_target, "error"),
                    lockfile_path=self.lock_file.source,
                    error_details="\n".join(
                        "{index}.) {platform}: {error}".format(
                            index=index, platform=target.platform.tag, error=error
                        )
                        for index, (target, error) in enumerate(error_by_target.items(), start=1)
                    ),
                ),
            )

        return LockUpdate(
            requirements=tuple(resolve_updater.iter_updated_requirements()),
            update_requirements_by_project_name=resolve_updater.update_requirements_by_project_name,
            resolves=tuple(
                ResolveUpdate(
                    updated_resolve=updated_resolve,
                    updates=resolve_updates_by_platform_tag.get(platform_tag, {}),
                )
                for platform_tag, updated_resolve in locked_resolve_by_platform_tag.items()
            ),
        )
