# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
from collections import OrderedDict

from pex.common import pluralize
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import Requirement
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.requirements import LocalProjectRequirement, parse_requirement_strings
from pex.resolve.locked_resolve import LockedResolve, Resolved
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import BuildConfiguration
from pex.result import Error
from pex.targets import Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, Generic

if TYPE_CHECKING:
    from typing import Dict, Iterable, List, Optional, Text, Tuple, TypeVar, Union

    import attr  # vendor:skip

    from pex.requirements import ParsedRequirement

    Source = TypeVar("Source")
else:
    from pex.third_party import attr


class Subset(Generic["Source"]):
    def __init__(
        self,
        target,  # type: Target
        resolved,  # type: Resolved[Source]
    ):
        # type: (...) -> None
        self.target = target
        self.resolved = resolved


class SubsetResult(Generic["Source"]):
    def __init__(
        self,
        requirements,  # type: Tuple[ParsedRequirement, ...]
        subsets,  # type: Tuple[Subset[Source], ...]
    ):
        # type: (...) -> None
        self.requirements = requirements
        self.subsets = subsets


def subset(
    targets,  # type: Targets
    lock,  # type: Lockfile
    requirement_configuration=RequirementConfiguration(),  # type: RequirementConfiguration
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    build_configuration=BuildConfiguration(),  # type: BuildConfiguration
    transitive=True,  # type: bool
    include_all_matches=False,  # type: bool
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> Union[SubsetResult[LockedResolve], Error]

    with TRACER.timed("Parsing requirements"):
        parsed_requirements = tuple(
            requirement_configuration.parse_requirements(network_configuration)
        ) or tuple(parse_requirement_strings(str(req) for req in lock.requirements))
        constraints = tuple(
            parsed_constraint.requirement
            for parsed_constraint in requirement_configuration.parse_constraints(
                network_configuration
            )
        )
        missing_local_projects = []  # type: List[Text]
        requirements_to_resolve = OrderedSet()  # type: OrderedSet[Requirement]
        for parsed_requirement in parsed_requirements:
            if isinstance(parsed_requirement, LocalProjectRequirement):
                local_project_requirement = lock.local_project_requirement_mapping.get(
                    os.path.abspath(parsed_requirement.path)
                )
                if local_project_requirement:
                    requirements_to_resolve.add(
                        attr.evolve(local_project_requirement, editable=parsed_requirement.editable)
                    )
                else:
                    missing_local_projects.append(parsed_requirement.line.processed_text)
            else:
                requirements_to_resolve.add(parsed_requirement.requirement)
        if missing_local_projects:
            return Error(
                "Found {count} local project {requirements} not present in the lock at {lock}:\n"
                "{missing}\n"
                "\n"
                "Perhaps{for_example} you meant to use `--project {project}`?".format(
                    count=len(missing_local_projects),
                    requirements=pluralize(missing_local_projects, "requirement"),
                    lock=lock.source,
                    missing="\n".join(
                        "{index}. {missing}".format(index=index, missing=missing)
                        for index, missing in enumerate(missing_local_projects, start=1)
                    ),
                    for_example=", as one example," if len(missing_local_projects) > 1 else "",
                    project=missing_local_projects[0],
                )
            )

    resolved_by_target = OrderedDict()  # type: OrderedDict[Target, Resolved[LockedResolve]]
    errors_by_target = {}  # type: Dict[Target, Iterable[Error]]

    with TRACER.timed(
        "Resolving urls to fetch for {count} requirements from lock {lockfile}".format(
            count=len(parsed_requirements), lockfile=lock.source
        )
    ):
        for target in targets.unique_targets():
            resolveds = []  # type: List[Resolved[LockedResolve]]
            errors = []
            for locked_resolve in lock.locked_resolves:
                # TODO(John Sirois): Handle --style universal subsets where target applicability
                #  needs to be looser. Maybe a custom Target type?:
                #  + requirement_applies
                #  + requires_python_applies
                #  + tags / wheel_applies -> may need to invert iter_compatible_artifacts into
                #    target to filter compatible artifacts.
                resolve_result = locked_resolve.resolve(
                    target,
                    requirements_to_resolve,
                    constraints=constraints,
                    source=lock.source,
                    build_configuration=build_configuration,
                    transitive=transitive,
                    include_all_matches=include_all_matches,
                    dependency_configuration=dependency_configuration,
                    # TODO(John Sirois): Plumb `--ignore-errors` to support desired but technically
                    #  invalid `pip-legacy-resolver` locks:
                    #  https://github.com/pex-tool/pex/issues/1652
                )
                if isinstance(resolve_result, Resolved):
                    resolveds.append(resolve_result)
                else:
                    errors.append(resolve_result)

            if resolveds:
                resolved_by_target[target] = Resolved.most_specific(resolveds)
            elif errors:
                errors_by_target[target] = tuple(errors)

    if errors_by_target:
        return Error(
            "Failed to resolve compatible artifacts from {lock} for {count} {targets}:\n"
            "{errors}".format(
                lock="lock {source}".format(source=lock.source) if lock.source else "lock",
                count=len(errors_by_target),
                targets=pluralize(errors_by_target, "target"),
                errors="\n".join(
                    "{index}. {target}:\n    {errors}".format(
                        index=index, target=target, errors="\n    ".join(map(str, errors))
                    )
                    for index, (target, errors) in enumerate(errors_by_target.items(), start=1)
                ),
            )
        )

    return SubsetResult[LockedResolve](
        requirements=parsed_requirements,
        subsets=tuple(
            Subset[LockedResolve](target=target, resolved=resolved)
            for target, resolved in resolved_by_target.items()
        ),
    )
