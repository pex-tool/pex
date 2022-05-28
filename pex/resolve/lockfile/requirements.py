# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.common import pluralize
from pex.dist_metadata import Requirement
from pex.network_configuration import NetworkConfiguration
from pex.requirements import (
    Constraint,
    LocalProjectRequirement,
    PyPIRequirement,
    URLRequirement,
    VCSRequirement,
    parse_requirement_strings,
)
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.result import Error
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, List, Optional, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Requirements(object):
    @classmethod
    def create(
        cls,
        parsed_requirements,  # type: Iterable[Union[PyPIRequirement, URLRequirement, VCSRequirement]]
        parsed_constraints,  # type: Iterable[Constraint]
    ):
        # type: (...) -> Requirements
        return cls(
            parsed_requirements=tuple(parsed_requirements),
            requirements=tuple(
                parsed_requirement.requirement for parsed_requirement in parsed_requirements
            ),
            parsed_constraints=tuple(parsed_constraints),
            constraints=tuple(
                parsed_constraint.requirement for parsed_constraint in parsed_constraints
            ),
        )

    parsed_requirements = (
        attr.ib()
    )  # type: Tuple[Union[PyPIRequirement, URLRequirement, VCSRequirement], ...]
    requirements = attr.ib()  # type: Tuple[Requirement, ...]
    parsed_constraints = attr.ib()  # type: Tuple[Constraint, ...]
    constraints = attr.ib()  # type: Tuple[Requirement, ...]


def parse_lockable_requirements(
    requirement_configuration,  # type: RequirementConfiguration
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    fallback_requirements=None,  # type: Optional[Iterable[str]]
):
    # type: (...) -> Union[Requirements, Error]

    all_parsed_requirements = requirement_configuration.parse_requirements(network_configuration)
    if not all_parsed_requirements and fallback_requirements:
        all_parsed_requirements = parse_requirement_strings(fallback_requirements)

    parsed_requirements = []  # type: List[Union[PyPIRequirement, URLRequirement, VCSRequirement]]
    projects = []  # type: List[str]
    for parsed_requirement in all_parsed_requirements:
        if isinstance(parsed_requirement, LocalProjectRequirement):
            projects.append("local project at {path}".format(path=parsed_requirement.path))
        else:
            parsed_requirements.append(parsed_requirement)
    if projects:
        return Error(
            "Cannot create a lock for project requirements built from local sources. Given {count} "
            "such {projects}:\n{project_descriptions}".format(
                count=len(projects),
                projects=pluralize(projects, "project"),
                project_descriptions="\n".join(
                    "{index}.) {project}".format(index=index, project=project)
                    for index, project in enumerate(projects, start=1)
                ),
            )
        )

    return Requirements.create(
        parsed_requirements=parsed_requirements,
        parsed_constraints=requirement_configuration.parse_constraints(network_configuration),
    )
