# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import re
from argparse import Namespace, _ActionsContainer
from collections import defaultdict

from pex.dist_metadata import Distribution, Requirement, RequirementParseError
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.pex_info import PexInfo
from pex.targets import Target
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import DefaultDict, Iterable, Mapping, Optional, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Override(object):
    class InvalidError(ValueError):
        pass

    @classmethod
    def parse(cls, override):
        # type: (str) -> Override

        project_name = None  # type: Optional[ProjectName]
        raw_requirement = override

        # See: https://peps.python.org/pep-0508/#names
        project_name_re = r"[A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9]"
        match = re.match(
            r"^(?P<project>{project_name_re})\s*=\s*(?P<requirement>{project_name_re}.*)$".format(
                project_name_re=project_name_re
            ),
            override,
            re.IGNORECASE,
        )
        if match:
            raw_project_name = match.group("project")
            raw_requirement = match.group("requirement")
            try:
                project_name = ProjectName(raw_project_name)
            except ProjectName.InvalidError as e:
                raise cls.InvalidError(
                    "Invalid project name {raw_project_name!r} in override {override!r}: "
                    "{err}".format(raw_project_name=raw_project_name, override=override, err=e)
                )
        try:
            requirement = Requirement.parse(raw_requirement)
        except RequirementParseError as e:
            raise cls.InvalidError(
                "Invalid override requirement {raw_requirement!r}: {err}".format(
                    raw_requirement=raw_requirement, err=e
                )
            )

        return cls(project_name=project_name or requirement.project_name, requirement=requirement)

    project_name = attr.ib()  # type: ProjectName
    requirement = attr.ib()  # type: Requirement

    def __str__(self):
        # type: () -> str

        if self.requirement.project_name == self.project_name:
            return str(self.requirement)

        return "{project_name}={requirement}".format(
            project_name=self.project_name, requirement=self.requirement
        )


@attr.s(frozen=True)
class DependencyConfiguration(object):
    @classmethod
    def create(
        cls,
        excluded=(),  # type: Iterable[Union[str, Requirement]]
        overridden=(),  # type: Iterable[Union[str, Override]]
    ):
        # type: (...) -> DependencyConfiguration

        overridden_projects = defaultdict(
            OrderedSet
        )  # type: DefaultDict[ProjectName, OrderedSet[Requirement]]
        for o in overridden:
            override = o if isinstance(o, Override) else Override.parse(o)
            overridden_projects[override.project_name].add(override.requirement)

        return cls(
            excluded=tuple(
                OrderedSet(
                    req if isinstance(req, Requirement) else Requirement.parse(req)
                    for req in excluded
                )
            ),
            overridden={
                project_name: tuple(overrides)
                for project_name, overrides in overridden_projects.items()
            },
        )

    @classmethod
    def from_pex_info(cls, pex_info):
        # type: (PexInfo) -> DependencyConfiguration
        return cls.create(pex_info.excluded, pex_info.overridden)

    excluded = attr.ib(default=())  # type: Tuple[Requirement, ...]
    overridden = attr.ib(factory=dict)  # type: Mapping[ProjectName, Tuple[Requirement, ...]]

    def configure(self, pex_info):
        # type: (PexInfo) -> None
        for excluded in self.excluded:
            pex_info.add_exclude(excluded)
        for project_name, overrides in self.overridden.items():
            for override in sorted(overrides, key=lambda req: req.key):
                pex_info.add_override(Override(project_name=project_name, requirement=override))

    def excluded_by(self, item):
        # type: (Union[Distribution, Requirement]) -> Tuple[Requirement, ...]
        return tuple(req for req in self.excluded if item in req)

    def all_overrides(self):
        # type: () -> Tuple[Override, ...]
        return tuple(
            Override(project_name=project_name, requirement=requirement)
            for project_name, requirements in self.overridden.items()
            for requirement in requirements
        )

    def overrides_for(self, requirement):
        # type: (Requirement) -> Tuple[Requirement, ...]
        return self.overridden.get(requirement.project_name, ())

    def overridden_by(
        self,
        requirement,  # type: Requirement
        target,  # type: Target
    ):
        # type: (...) -> Optional[Requirement]
        overrides = self.overrides_for(requirement)
        applicable_overrides = [
            override for override in overrides if target.requirement_applies(override)
        ]
        if len(applicable_overrides) > 1:
            raise ValueError(
                "Invalid override configuration for target {target}.\n"
                "More than one applicable override was found for {requirement}:\n"
                "{overrides}".format(
                    requirement=repr(str(requirement)),
                    target=target.render_description(),
                    overrides="\n".join(
                        "{index}. {override}".format(index=index, override=repr(str(override)))
                        for index, override in enumerate(applicable_overrides, start=1)
                    ),
                )
            )
        return applicable_overrides[0] if applicable_overrides else None

    def merge(self, other):
        # type: (DependencyConfiguration) -> DependencyConfiguration

        excluded = OrderedSet(self.excluded)
        excluded.update(other.excluded)

        overridden = defaultdict(
            OrderedSet
        )  # type: DefaultDict[ProjectName, OrderedSet[Requirement]]
        for project_name, overrides in itertools.chain(
            self.overridden.items(), other.overridden.items()
        ):
            overridden[project_name].update(overrides)

        return DependencyConfiguration(
            excluded=tuple(excluded),
            overridden={
                project_name: tuple(overrides) for project_name, overrides in overridden.items()
            },
        )


def register(parser):
    # type: (_ActionsContainer) -> None
    """Register dependency configuration options with the given parser.

    :param parser: The parser to register dependency configuration options with.
    """
    parser.add_argument(
        "--exclude",
        dest="excluded",
        default=[],
        type=str,
        action="append",
        help=(
            "Specifies a requirement to exclude from the built PEX. Any distribution included in "
            "the PEX's resolve that matches the requirement is excluded from the built PEX along "
            "with all of its transitive dependencies that are not also required by other "
            "non-excluded distributions. At runtime, the PEX will boot without checking the "
            "excluded dependencies are available (say, via `--inherit-path`). This option can be "
            "used multiple times."
        ),
    )
    parser.add_argument(
        "--override",
        dest="overridden",
        default=[],
        type=str,
        action="append",
        help=(
            "Specifies a transitive requirement to override when resolving. Overrides can either "
            "modify an existing dependency on a project name by changing extras, version "
            "constraints or markers or else they can completely swap out the dependency for a "
            "dependency on another project altogether. For the former, simply supply the "
            "requirement you wish. For example, specifying `--override cowsay==5.0` will override "
            "any transitive dependency on cowsay that has any combination of extras, version "
            "constraints or markers with the requirement `cowsay==5.0`. To completely replace "
            "cowsay with another library altogether, you can specify an override like "
            "`--override cowsay=my-cowsay>2`. This will replace any transitive dependency on "
            "cowsay that has any combination of extras, version constraints or markers with the "
            "requirement `my-cowsay>2`. This option can be used multiple times."
        ),
    )


def configure(options):
    # type: (Namespace) -> DependencyConfiguration
    """Creates a dependency configuration from options registered by `register`."""

    return DependencyConfiguration.create(excluded=options.excluded, overridden=options.overridden)
