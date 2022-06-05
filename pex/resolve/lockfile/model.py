# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os

from pex.dist_metadata import Requirement
from pex.orderedset import OrderedSet
from pex.requirements import LocalProjectRequirement
from pex.resolve.locked_resolve import LocalProjectArtifact, LockedResolve, LockStyle, Resolved
from pex.resolve.resolver_configuration import ResolverVersion
from pex.sorted_tuple import SortedTuple
from pex.targets import Target
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Tuple, Union

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
        resolver_version,  # type: ResolverVersion.Value
        requirements,  # type: Iterable[Union[Requirement, ParsedRequirement]]
        constraints,  # type: Iterable[Requirement]
        allow_prereleases,  # type: bool
        allow_wheels,  # type: bool
        allow_builds,  # type: bool
        prefer_older_binary,  # type: bool
        use_pep517,  # type: Optional[bool]
        build_isolation,  # type: bool
        transitive,  # type: bool
        locked_resolves,  # type: Iterable[LockedResolve]
        source=None,  # type: Optional[str]
    ):
        # type: (...) -> Lockfile

        pin_by_local_project_directory = {
            locked_requirement.artifact.directory: locked_requirement.pin
            for locked_resolve in locked_resolves
            for locked_requirement in locked_resolve.locked_requirements
            if isinstance(locked_requirement.artifact, LocalProjectArtifact)
        }
        requirement_by_local_project_directory = {}  # type: Dict[str, Requirement]

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
                requirement_by_local_project_directory[local_project_directory] = requirement
                return requirement
            return req.requirement

        resolve_requirements = OrderedSet(extract_requirement(req) for req in requirements)

        return cls(
            pex_version=pex_version,
            style=style,
            requires_python=SortedTuple(requires_python),
            resolver_version=resolver_version,
            requirements=SortedTuple(resolve_requirements, key=str),
            constraints=SortedTuple(constraints, key=str),
            allow_prereleases=allow_prereleases,
            allow_wheels=allow_wheels,
            allow_builds=allow_builds,
            prefer_older_binary=prefer_older_binary,
            use_pep517=use_pep517,
            build_isolation=build_isolation,
            transitive=transitive,
            locked_resolves=SortedTuple(locked_resolves),
            local_project_requirement_mapping=requirement_by_local_project_directory,
            source=source,
        )

    pex_version = attr.ib()  # type: str
    style = attr.ib()  # type: LockStyle.Value
    requires_python = attr.ib()  # type: SortedTuple[str]
    resolver_version = attr.ib()  # type: ResolverVersion.Value
    requirements = attr.ib()  # type: SortedTuple[Requirement]
    constraints = attr.ib()  # type: SortedTuple[Requirement]
    allow_prereleases = attr.ib()  # type: bool
    allow_wheels = attr.ib()  # type: bool
    allow_builds = attr.ib()  # type: bool
    prefer_older_binary = attr.ib()  # type: bool
    use_pep517 = attr.ib()  # type: Optional[bool]
    build_isolation = attr.ib()  # type: bool
    transitive = attr.ib()  # type: bool
    locked_resolves = attr.ib()  # type: SortedTuple[LockedResolve]
    local_project_requirement_mapping = attr.ib()  # type: Mapping[str, Requirement]
    source = attr.ib(default=None, eq=False)  # type: Optional[str]

    def select(self, targets):
        # type: (Iterable[Target]) -> Iterator[Tuple[Target, LockedResolve]]
        """Finds the most appropriate lock, if any, for each of the given targets.

        :param targets: The targets to select locked resolves for.
        :return: The selected locks.
        """
        for target in targets:
            lock = self._select(target)
            if lock:
                yield target, lock

    def _select(self, target):
        # type: (Target) -> Optional[LockedResolve]
        resolves = []  # type: List[Tuple[float, LockedResolve]]
        for locked_resolve in self.locked_resolves:
            result = locked_resolve.resolve(target, self.requirements)
            if isinstance(result, Resolved):
                resolves.append((result.target_specificity, locked_resolve))

        if not resolves:
            return None

        target_specificity, locked_resolve = sorted(resolves)[-1]
        TRACER.log(
            "Selected lock generated by {platform} with an average artifact platform specificity "
            "of ~{percent:.1%} from locks generated by {platforms}".format(
                platform=locked_resolve.platform_tag or "universal",
                percent=target_specificity,
                platforms=", ".join(
                    sorted(str(lock.platform_tag) for lock in self.locked_resolves)
                ),
            )
        )
        return locked_resolve
