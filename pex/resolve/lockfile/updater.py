# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import logging
import os
from collections import OrderedDict
from contextlib import contextmanager

from pex.common import pluralize
from pex.network_configuration import NetworkConfiguration
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import LockConfiguration, LockedRequirement, LockedResolve
from pex.resolve.lockfile import Lockfile, create
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import PipConfiguration, ReposConfiguration
from pex.result import Error, ResultError, catch, try_
from pex.sorted_tuple import SortedTuple
from pex.targets import AbbreviatedPlatform, LocalInterpreter, Target, Targets
from pex.third_party.packaging import tags
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING
from pex.util import named_temporary_file

if TYPE_CHECKING:
    from typing import Dict, Iterable, Iterator, Mapping, Optional, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


logger = logging.getLogger(__name__)


@attr.s(frozen=True)
class VersionUpdate(object):
    original = attr.ib()  # type: Version
    updated = attr.ib()  # type: Version


@attr.s(frozen=True)
class ResolveUpdate(object):
    updated_resolve = attr.ib()  # type: LockedResolve
    updates = attr.ib()  # type: Mapping[ProjectName, Optional[VersionUpdate]]


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
    def create(
        cls,
        requirements,  # type: Iterable[Requirement]
        constraints,  # type: Iterable[Requirement]
        updates,  # type: Iterable[Requirement]
        lock_configuration,  # type: LockConfiguration
        pip_configuration,  # type: PipConfiguration
    ):
        original_requirements = tuple(str(requirement) for requirement in requirements)

        original_constraints = {
            ProjectName(constraint.project_name): constraint for constraint in constraints
        }  # type: Mapping[ProjectName, Requirement]

        update_constraints_by_project_name = {}  # type: Dict[ProjectName, Requirement]
        for update in updates:
            project_name = ProjectName(update.project_name)
            original_constraint = original_constraints.get(project_name)
            if original_constraint:
                logger.warning(
                    "Over-riding original constraint {original} with {override}.".format(
                        original=original_constraint, override=update
                    )
                )
            update_constraints_by_project_name[project_name] = update

        return cls(
            update_constraints_by_project_name=update_constraints_by_project_name,
            lock_configuration=lock_configuration,
            original_requirements=original_requirements,
            pip_configuration=pip_configuration,
        )

    original_requirements = attr.ib()  # type: Iterable[str]
    update_constraints_by_project_name = attr.ib()  # type: Mapping[ProjectName, Requirement]
    lock_configuration = attr.ib()  # type: LockConfiguration
    pip_configuration = attr.ib()  # type: PipConfiguration

    @contextmanager
    def _calculate_update_constraints(self, locked_resolve):
        # type: (LockedResolve) -> Iterator[Optional[Iterable[str]]]
        if not self.update_constraints_by_project_name:
            yield None
            return

        constraints = []
        for locked_requirement in locked_resolve.locked_requirements:
            pin = locked_requirement.pin
            constraint = self.update_constraints_by_project_name.get(
                pin.project_name, pin.as_requirement()
            )
            constraints.append(str(constraint))
        if not constraints:
            yield None
            return

        with named_temporary_file(prefix="lock_update.", suffix=".constraints.txt", mode="w") as fp:
            fp.write(os.linesep.join(constraints))
            fp.flush()
            try:
                yield [fp.name]
            except ResultError as e:
                logger.error(
                    "The following lock update constraints could not be satisfied:\n"
                    "{constraints}".format(constraints="\n".join(constraints))
                )
                raise e

    def update_resolve(
        self,
        locked_resolve,  # type: LockedResolve
        targets,  # type: Targets
    ):
        # type: (...) -> Union[ResolveUpdate, Error]

        with self._calculate_update_constraints(locked_resolve) as constraints_files:
            updated_lock_file = try_(
                create(
                    lock_configuration=self.lock_configuration,
                    requirement_configuration=RequirementConfiguration(
                        requirements=self.original_requirements,
                        constraint_files=constraints_files,
                    ),
                    targets=targets,
                    pip_configuration=self.pip_configuration,
                )
            )

        assert 1 == len(updated_lock_file.locked_resolves)
        updated_resolve = updated_lock_file.locked_resolves[0]

        updated_requirements_by_project_name = OrderedDict(
            (updated_requirement.pin.project_name, updated_requirement)
            for updated_requirement in updated_resolve.locked_requirements
        )  # type: OrderedDict[ProjectName, LockedRequirement]

        updates = OrderedDict()  # type: OrderedDict[ProjectName, Optional[VersionUpdate]]
        for locked_requirement in locked_resolve.locked_requirements:
            original_pin = locked_requirement.pin
            project_name = original_pin.project_name
            updated_requirement = updated_requirements_by_project_name.get(project_name)
            if not updated_requirement:
                continue
            updated_pin = updated_requirement.pin
            if (
                self.update_constraints_by_project_name
                and project_name not in self.update_constraints_by_project_name
            ):
                assert updated_pin == original_pin
                assert updated_requirement.artifact == locked_requirement.artifact
                assert (
                    updated_requirement.additional_artifacts
                    == locked_requirement.additional_artifacts
                )
            elif original_pin != updated_pin:
                updates[project_name] = VersionUpdate(
                    original=original_pin.version, updated=updated_pin.version
                )
            elif project_name in self.update_constraints_by_project_name:
                updates[project_name] = None

        return ResolveUpdate(
            updated_resolve=attr.evolve(
                locked_resolve,
                locked_requirements=SortedTuple(updated_requirements_by_project_name.values()),
            ),
            updates=updates,
        )


@attr.s(frozen=True)
class ResolveUpdateRequest(object):
    target = attr.ib()  # type: Target
    locked_resolve = attr.ib()  # type: LockedResolve

    def targets(self, assume_manylinux=None):
        # type: (Optional[str]) -> Targets
        return Targets(
            interpreters=(self.target.interpreter,)
            if isinstance(self.target, LocalInterpreter)
            else (),
            platforms=(self.target.platform,)
            if isinstance(self.target, AbbreviatedPlatform)
            else (),
            assume_manylinux=assume_manylinux,
        )


@attr.s(frozen=True)
class LockUpdate(object):
    resolves = attr.ib()  # type: Iterable[ResolveUpdate]


@attr.s(frozen=True)
class LockUpdater(object):
    @classmethod
    def create(
        cls,
        lock_file,  # type: Lockfile
        repos_configuration,  # type: ReposConfiguration
        network_configuration,  # type: NetworkConfiguration
        max_jobs,  # type: int
    ):
        # type: (...) -> LockUpdater

        lock_configuration = LockConfiguration(
            style=lock_file.style, requires_python=lock_file.requires_python
        )
        pip_configuration = PipConfiguration(
            resolver_version=lock_file.resolver_version,
            allow_prereleases=lock_file.allow_prereleases,
            allow_wheels=lock_file.allow_wheels,
            allow_builds=lock_file.allow_builds,
            prefer_older_binary=lock_file.prefer_older_binary,
            use_pep517=lock_file.use_pep517,
            build_isolation=lock_file.build_isolation,
            transitive=lock_file.transitive,
            repos_configuration=repos_configuration,
            network_configuration=network_configuration,
            max_jobs=max_jobs,
        )
        return cls(
            lock_file=lock_file,
            lock_configuration=lock_configuration,
            pip_configuration=pip_configuration,
        )

    lock_file = attr.ib()  # type: Lockfile
    lock_configuration = attr.ib()  # type: LockConfiguration
    pip_configuration = attr.ib()  # type: PipConfiguration

    def update(
        self,
        update_requests,  # type: Iterable[ResolveUpdateRequest]
        updates,  # type: Iterable[Requirement]
        assume_manylinux=None,  # type: Optional[str]
    ):
        # type: (...) -> Union[LockUpdate, Error]

        resolve_updater = ResolveUpdater.create(
            requirements=self.lock_file.requirements,
            constraints=self.lock_file.constraints,
            updates=updates,
            lock_configuration=self.lock_configuration,
            pip_configuration=self.pip_configuration,
        )

        error_by_target = OrderedDict()  # type: OrderedDict[Target, Error]
        locked_resolve_by_platform_tag = OrderedDict(
            (locked_resolve.platform_tag, locked_resolve)
            for locked_resolve in self.lock_file.locked_resolves
        )  # type: OrderedDict[tags.Tag, LockedResolve]
        resolve_updates_by_platform_tag = (
            {}
        )  # type: Dict[tags.Tag, Mapping[ProjectName, Optional[VersionUpdate]]]

        # TODO(John Sirois): Consider parallelizing this. The underlying Jobs are down a few layers;
        #  so this will likely require using multiprocessing.
        for update_request in update_requests:
            result = catch(
                resolve_updater.update_resolve,
                locked_resolve=update_request.locked_resolve,
                targets=update_request.targets(assume_manylinux=assume_manylinux),
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
            resolves=tuple(
                ResolveUpdate(
                    updated_resolve=updated_resolve,
                    updates=resolve_updates_by_platform_tag.get(platform_tag, {}),
                )
                for platform_tag, updated_resolve in locked_resolve_by_platform_tag.items()
            )
        )
