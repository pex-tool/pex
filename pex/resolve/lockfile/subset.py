# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
from collections import OrderedDict

from pex.common import pluralize
from pex.exclude_configuration import ExcludeConfiguration
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.requirements import LocalProjectRequirement, parse_requirement_strings
from pex.resolve.locked_resolve import Resolved
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import BuildConfiguration
from pex.result import Error
from pex.targets import Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, Iterable, Optional, Tuple, Union

    import attr  # vendor:skip

    from pex.requirements import ParsedRequirement
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Subset(object):
    target = attr.ib()  # type: Target
    resolved = attr.ib()  # type: Resolved


@attr.s(frozen=True)
class SubsetResult(object):
    requirements = attr.ib()  # type: Tuple[ParsedRequirement, ...]
    subsets = attr.ib()  # type: Tuple[Subset, ...]


def subset(
    targets,  # type: Targets
    lock,  # type: Lockfile
    requirement_configuration=RequirementConfiguration(),  # type: RequirementConfiguration
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    build_configuration=BuildConfiguration(),  # type: BuildConfiguration
    transitive=True,  # type: bool
    include_all_matches=False,  # type: bool
    exclude_configuration=ExcludeConfiguration(),  # type: ExcludeConfiguration
):
    # type: (...) -> Union[SubsetResult, Error]

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
        requirements_to_resolve = OrderedSet(
            lock.local_project_requirement_mapping[os.path.abspath(parsed_requirement.path)]
            if isinstance(parsed_requirement, LocalProjectRequirement)
            else parsed_requirement.requirement
            for parsed_requirement in parsed_requirements
        )

    resolved_by_target = OrderedDict()  # type: OrderedDict[Target, Resolved]
    errors_by_target = {}  # type: Dict[Target, Iterable[Error]]

    with TRACER.timed(
        "Resolving urls to fetch for {count} requirements from lock {lockfile}".format(
            count=len(parsed_requirements), lockfile=lock.source
        )
    ):
        for target in targets.unique_targets():
            resolveds = []
            errors = []
            for locked_resolve in lock.locked_resolves:
                resolve_result = locked_resolve.resolve(
                    target,
                    requirements_to_resolve,
                    constraints=constraints,
                    source=lock.source,
                    build_configuration=build_configuration,
                    transitive=transitive,
                    include_all_matches=include_all_matches,
                    exclude_configuration=exclude_configuration,
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

    return SubsetResult(
        requirements=parsed_requirements,
        subsets=tuple(
            Subset(target=target, resolved=resolved)
            for target, resolved in resolved_by_target.items()
        ),
    )
