# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.fetcher import URLFetcher
from pex.network_configuration import NetworkConfiguration
from pex.requirements import Constraint, parse_requirement_file, parse_requirement_strings
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import Optional, Iterable, List
    from pex.requirements import ParsedRequirement
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class RequirementConfiguration(object):
    requirements = attr.ib(default=None)  # type: Optional[Iterable[str]]
    requirement_files = attr.ib(default=None)  # type: Optional[Iterable[str]]
    constraint_files = attr.ib(default=None)  # type: Optional[Iterable[str]]

    def parse_requirements(self, network_configuration=None):
        # type: (Optional[NetworkConfiguration]) -> Iterable[ParsedRequirement]
        parsed_requirements = []  # type: List[ParsedRequirement]
        if self.requirements:
            parsed_requirements.extend(parse_requirement_strings(self.requirements))
        if self.requirement_files:
            fetcher = URLFetcher(network_configuration=network_configuration)
            for requirement_file in self.requirement_files:
                parsed_requirements.extend(
                    requirement_or_constraint
                    for requirement_or_constraint in parse_requirement_file(
                        requirement_file, is_constraints=False, fetcher=fetcher
                    )
                    if not isinstance(requirement_or_constraint, Constraint)
                )
        return parsed_requirements

    def parse_constraints(self, network_configuration=None):
        # type: (Optional[NetworkConfiguration]) -> Iterable[Constraint]
        parsed_constraints = []  # type: List[Constraint]
        if self.constraint_files:
            fetcher = URLFetcher(network_configuration=network_configuration)
            for constraint_file in self.constraint_files:
                parsed_constraints.extend(
                    requirement_or_constraint
                    for requirement_or_constraint in parse_requirement_file(
                        constraint_file, is_constraints=True, fetcher=fetcher
                    )
                    if isinstance(requirement_or_constraint, Constraint)
                )
        return parsed_constraints
