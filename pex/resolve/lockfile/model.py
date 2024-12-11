# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os

from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import Constraint, Requirement
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.pip.version import PipVersion, PipVersionValue
from pex.requirements import LocalProjectRequirement
from pex.resolve.locked_resolve import (
    LocalProjectArtifact,
    LockConfiguration,
    LockedResolve,
    LockStyle,
    TargetSystem,
)
from pex.resolve.lockfile import requires_dist
from pex.resolve.resolved_requirement import Pin
from pex.resolve.resolver_configuration import BuildConfiguration, ResolverVersion
from pex.sorted_tuple import SortedTuple
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, Iterable, Mapping, Optional, Union

    import attr  # vendor:skip

    from pex.requirements import ParsedRequirement
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Lockfile(object):
    @classmethod
    def create(
        cls,
        pex_version,  # type: str
        style,  # type: LockStyle.Value
        requires_python,  # type: Iterable[str]
        target_systems,  # type: Iterable[TargetSystem.Value]
        requirements,  # type: Iterable[Union[Requirement, ParsedRequirement]]
        constraints,  # type: Iterable[Constraint]
        allow_prereleases,  # type: bool
        build_configuration,  # type: BuildConfiguration
        transitive,  # type: bool
        excluded,  # type: Iterable[Requirement]
        overridden,  # type: Iterable[Requirement]
        locked_resolves,  # type: Iterable[LockedResolve]
        source=None,  # type: Optional[str]
        pip_version=None,  # type: Optional[PipVersionValue]
        resolver_version=None,  # type: Optional[ResolverVersion.Value]
        elide_unused_requires_dist=False,  # type: bool
    ):
        # type: (...) -> Lockfile

        pin_by_local_project_directory = {}  # type: Dict[str, Pin]
        requirement_by_local_project_directory = {}  # type: Dict[str, Requirement]
        for locked_resolve in locked_resolves:
            for locked_requirement in locked_resolve.locked_requirements:
                if isinstance(locked_requirement.artifact, LocalProjectArtifact):
                    local_directory = locked_requirement.artifact.directory
                    local_pin = locked_requirement.pin
                    pin_by_local_project_directory[local_directory] = local_pin
                    requirement_by_local_project_directory[
                        local_directory
                    ] = local_pin.as_requirement()

        def extract_requirement(req):
            # type: (Union[Requirement, ParsedRequirement]) -> Requirement
            if isinstance(req, Requirement):
                return req
            if isinstance(req, LocalProjectRequirement):
                local_project_directory = os.path.abspath(req.path)
                pin = pin_by_local_project_directory[local_project_directory]
                requirement = Requirement.parse(
                    "{project_name}{extras}=={version}{marker}".format(
                        project_name=pin.project_name,
                        extras="[{extras}]".format(extras=",".join(req.extras))
                        if req.extras
                        else "",
                        version=pin.version,
                        marker="; {marker}".format(marker=req.marker) if req.marker else "",
                    )
                )
                # N.B.: We've already mapped all available local projects above, but the user may
                # have supplied the local project requirement with more specific constraints (
                # extras and / or marker restrictions) and we need to honor those; so we over-write.
                requirement_by_local_project_directory[local_project_directory] = requirement
                return requirement
            return req.requirement

        resolve_requirements = OrderedSet(extract_requirement(req) for req in requirements)

        pip_ver = pip_version or PipVersion.DEFAULT
        return cls(
            pex_version=pex_version,
            style=style,
            requires_python=SortedTuple(requires_python),
            target_systems=SortedTuple(target_systems),
            elide_unused_requires_dist=elide_unused_requires_dist,
            pip_version=pip_ver,
            resolver_version=resolver_version or ResolverVersion.default(pip_ver),
            requirements=SortedTuple(resolve_requirements, key=str),
            constraints=SortedTuple(constraints, key=str),
            allow_prereleases=allow_prereleases,
            allow_wheels=build_configuration.allow_wheels,
            only_wheels=SortedTuple(build_configuration.only_wheels),
            allow_builds=build_configuration.allow_builds,
            only_builds=SortedTuple(build_configuration.only_builds),
            prefer_older_binary=build_configuration.prefer_older_binary,
            use_pep517=build_configuration.use_pep517,
            build_isolation=build_configuration.build_isolation,
            use_system_time=build_configuration.use_system_time,
            transitive=transitive,
            excluded=SortedTuple(excluded),
            overridden=SortedTuple(overridden),
            locked_resolves=SortedTuple(
                (
                    requires_dist.remove_unused_requires_dist(resolve_requirements, locked_resolve)
                    if elide_unused_requires_dist
                    else locked_resolve
                )
                for locked_resolve in locked_resolves
            ),
            local_project_requirement_mapping=requirement_by_local_project_directory,
            source=source,
        )

    pex_version = attr.ib()  # type: str
    style = attr.ib()  # type: LockStyle.Value
    requires_python = attr.ib()  # type: SortedTuple[str]
    target_systems = attr.ib()  # type: SortedTuple[TargetSystem.Value]
    elide_unused_requires_dist = attr.ib()  # type: bool
    pip_version = attr.ib()  # type: PipVersionValue
    resolver_version = attr.ib()  # type: ResolverVersion.Value
    requirements = attr.ib()  # type: SortedTuple[Requirement]
    constraints = attr.ib()  # type: SortedTuple[Constraint]
    allow_prereleases = attr.ib()  # type: bool
    allow_wheels = attr.ib()  # type: bool
    only_wheels = attr.ib()  # type: SortedTuple[ProjectName]
    allow_builds = attr.ib()  # type: bool
    only_builds = attr.ib()  # type: SortedTuple[ProjectName]
    prefer_older_binary = attr.ib()  # type: bool
    use_pep517 = attr.ib()  # type: Optional[bool]
    build_isolation = attr.ib()  # type: bool
    use_system_time = attr.ib()  # type: bool
    transitive = attr.ib()  # type: bool
    excluded = attr.ib()  # type: SortedTuple[Requirement]
    overridden = attr.ib()  # type: SortedTuple[Requirement]
    locked_resolves = attr.ib()  # type: SortedTuple[LockedResolve]
    local_project_requirement_mapping = attr.ib(eq=False)  # type: Mapping[str, Requirement]
    source = attr.ib(default=None, eq=False)  # type: Optional[str]

    def lock_configuration(self):
        # type: () -> LockConfiguration
        return LockConfiguration(
            style=self.style,
            requires_python=self.requires_python,
            target_systems=self.target_systems,
            elide_unused_requires_dist=self.elide_unused_requires_dist,
        )

    def build_configuration(self):
        # type: () -> BuildConfiguration
        return BuildConfiguration.create(
            allow_builds=self.allow_builds,
            only_builds=self.only_builds,
            allow_wheels=self.allow_wheels,
            only_wheels=self.only_wheels,
            prefer_older_binary=self.prefer_older_binary,
            use_pep517=self.use_pep517,
            build_isolation=self.build_isolation,
            use_system_time=self.use_system_time,
        )

    def dependency_configuration(self):
        # type: () -> DependencyConfiguration
        return DependencyConfiguration.create(excluded=self.excluded, overridden=self.overridden)
