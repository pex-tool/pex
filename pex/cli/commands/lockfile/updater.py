# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import logging
import os
from collections import OrderedDict
from contextlib import contextmanager

from pex.cli.commands.lockfile import create
from pex.commands.command import Error, ResultError, try_
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import LockConfiguration, LockedRequirement, LockedResolve, Version
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolve.target_configuration import TargetConfiguration
from pex.sorted_tuple import SortedTuple
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING
from pex.util import named_temporary_file

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import Dict, Iterable, Iterator, Mapping, Optional, Union
else:
    from pex.third_party import attr


logger = logging.getLogger(__name__)


@attr.s(frozen=True)
class VersionUpdate(object):
    original = attr.ib()  # type: Version
    updated = attr.ib()  # type: Version


@attr.s(frozen=True)
class LockUpdate(object):
    updated_resolve = attr.ib()  # type: LockedResolve
    updates = attr.ib()  # type: Mapping[ProjectName, Optional[VersionUpdate]]


@attr.s(frozen=True)
class LockUpdater(object):
    """Updates a lockfile in whole or in part.

    A lock updater with no updates specified just updates the whole lock file with the latest
    available distributions that satisfy the locked resolve criteria.

    More interestingly, a lock updater with a set of updates will attempt to alter just the
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
            constraint_req = Requirement.parse(update)
            project_name = ProjectName(constraint_req.project_name)
            original_constraint = original_constraints.get(project_name)
            if original_constraint:
                logger.warning(
                    "Over-riding original constraint {original} with {override}.".format(
                        original=original_constraint, override=constraint_req
                    )
                )
            update_constraints_by_project_name[project_name] = constraint_req

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

    def _log(self, message):
        if self.dry_run:
            print(message)
        else:
            logger.info(message)

    def update_resolve(
        self,
        locked_resolve,  # type: LockedResolve
        target_configuration,  # type: TargetConfiguration
    ):
        # type: (...) -> Union[LockUpdate, Error]

        with self._calculate_update_constraints(locked_resolve) as constraints_files:
            updated_lock_file = try_(
                create(
                    lock_configuration=self.lock_configuration,
                    requirement_configuration=RequirementConfiguration(
                        requirements=self.original_requirements,
                        constraint_files=constraints_files,
                    ),
                    target_configuration=target_configuration,
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

            updated_requirements_by_project_name[project_name] = attr.evolve(
                updated_requirement,
                requirement=locked_requirement.requirement,
                via=locked_requirement.via,
            )

        return LockUpdate(
            updated_resolve=attr.evolve(
                locked_resolve,
                locked_requirements=SortedTuple(updated_requirements_by_project_name.values()),
            ),
            updates=updates,
        )
