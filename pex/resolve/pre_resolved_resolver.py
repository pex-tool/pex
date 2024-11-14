# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import os
from collections import defaultdict

from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import Distribution, Requirement
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.interpreter import PythonInterpreter
from pex.jobs import iter_map_parallel
from pex.orderedset import OrderedSet
from pex.pep_427 import InstallableType
from pex.pep_503 import ProjectName
from pex.pip.tool import PackageIndexConfiguration
from pex.requirements import LocalProjectRequirement
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.locked_resolve import Artifact, FileArtifact, LockedRequirement, LockedResolve
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolved_requirement import ArtifactURL, Fingerprint, Pin
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolve.resolvers import (
    ResolvedDistribution,
    ResolveResult,
    check_resolve,
    sorted_requirements,
)
from pex.resolver import BuildAndInstallRequest, BuildRequest, InstallRequest
from pex.result import try_
from pex.sorted_tuple import SortedTuple
from pex.targets import Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper

if TYPE_CHECKING:
    from typing import DefaultDict, Dict, Iterable, List, Tuple


def _fingerprint_dist(dist_path):
    # type: (str) -> Tuple[str, str]
    return dist_path, CacheHelper.hash(dist_path, hasher=hashlib.sha256)


def resolve_from_dists(
    targets,  # type: Targets
    sdists,  # type: Iterable[str]
    wheels,  # type: Iterable[str]
    requirement_configuration,  # type: RequirementConfiguration
    pip_configuration=PipConfiguration(),  # type: PipConfiguration
    compile=False,  # type: bool
    ignore_errors=False,  # type: bool
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> ResolveResult

    unique_targets = targets.unique_targets()

    direct_requirements = requirement_configuration.parse_requirements(
        pip_configuration.network_configuration
    )
    local_projects = []  # type: List[LocalProjectRequirement]
    for direct_requirement in direct_requirements:
        if isinstance(direct_requirement, LocalProjectRequirement):
            local_projects.append(direct_requirement)

    source_paths = [local_project.path for local_project in local_projects] + list(
        sdists
    )  # type: List[str]
    with TRACER.timed("Fingerprinting pre-resolved wheels"):
        fingerprinted_wheels = tuple(
            FingerprintedDistribution(
                distribution=Distribution.load(dist_path), fingerprint=fingerprint
            )
            for dist_path, fingerprint in iter_map_parallel(
                inputs=wheels,
                function=_fingerprint_dist,
                max_jobs=pip_configuration.max_jobs,
                costing_function=lambda whl: os.path.getsize(whl),
                noun="wheel",
                verb="fingerprint",
                verb_past="fingerprinted",
            )
        )

    resolved_dists = []  # type: List[ResolvedDistribution]
    resolve_installed_wheel_chroots = (
        fingerprinted_wheels and InstallableType.INSTALLED_WHEEL_CHROOT is result_type
    )
    with TRACER.timed("Preparing pre-resolved distributions"):
        if source_paths or resolve_installed_wheel_chroots:
            package_index_configuration = PackageIndexConfiguration.create(
                pip_version=pip_configuration.version,
                resolver_version=pip_configuration.resolver_version,
                indexes=pip_configuration.repos_configuration.indexes,
                find_links=pip_configuration.repos_configuration.find_links,
                network_configuration=pip_configuration.network_configuration,
                password_entries=pip_configuration.repos_configuration.password_entries,
                use_pip_config=pip_configuration.use_pip_config,
                extra_pip_requirements=pip_configuration.extra_requirements,
                keyring_provider=pip_configuration.keyring_provider,
            )
            build_and_install = BuildAndInstallRequest(
                build_requests=[
                    BuildRequest.create(target=target, source_path=source_path)
                    for source_path in source_paths
                    for target in unique_targets
                ],
                install_requests=[
                    InstallRequest(
                        target=target, wheel_path=wheel.location, fingerprint=wheel.fingerprint
                    )
                    for wheel in fingerprinted_wheels
                    for target in unique_targets
                ],
                direct_requirements=direct_requirements,
                package_index_configuration=package_index_configuration,
                compile=compile,
                build_configuration=pip_configuration.build_configuration,
                verify_wheels=True,
                pip_version=pip_configuration.version,
                resolver=ConfiguredResolver(pip_configuration=pip_configuration),
                dependency_configuration=dependency_configuration,
            )
            resolved_dists.extend(
                build_and_install.install_distributions(
                    ignore_errors=ignore_errors,
                    max_parallel_jobs=pip_configuration.max_jobs,
                )
                if resolve_installed_wheel_chroots
                else build_and_install.build_distributions(
                    ignore_errors=ignore_errors,
                    max_parallel_jobs=pip_configuration.max_jobs,
                )
            )
        elif wheels:
            direct_reqs_by_project_name = defaultdict(
                list
            )  # type: DefaultDict[ProjectName, List[Requirement]]
            for parsed_req in direct_requirements:
                assert not isinstance(parsed_req, LocalProjectRequirement)
                direct_reqs_by_project_name[parsed_req.requirement.project_name].append(
                    parsed_req.requirement
                )
            for wheel in fingerprinted_wheels:
                direct_reqs = sorted_requirements(direct_reqs_by_project_name[wheel.project_name])
                for target in unique_targets:
                    resolved_dists.append(
                        ResolvedDistribution(
                            target=target,
                            fingerprinted_distribution=wheel,
                            direct_requirements=direct_reqs,
                        )
                    )
            if not ignore_errors:
                check_resolve(dependency_configuration, resolved_dists)

    with TRACER.timed("Sub-setting pre-resolved wheels"):
        root_requirements = OrderedSet()  # type: OrderedSet[Requirement]
        locked_requirements = []  # type: List[LockedRequirement]
        resolved_dist_by_file_artifact = {}  # type: Dict[Artifact, ResolvedDistribution]
        for resolved_dist in resolved_dists:
            file_artifact = FileArtifact(
                url=ArtifactURL.parse(resolved_dist.distribution.location),
                fingerprint=Fingerprint(algorithm="sha256", hash=resolved_dist.fingerprint),
                verified=True,
                filename=os.path.basename(resolved_dist.distribution.location),
            )
            dist_metadata = resolved_dist.distribution.metadata
            locked_requirements.append(
                LockedRequirement.create(
                    pin=Pin(
                        project_name=dist_metadata.project_name,
                        version=dist_metadata.version,
                    ),
                    artifact=file_artifact,
                    requires_python=dist_metadata.requires_python,
                    requires_dists=dist_metadata.requires_dists,
                )
            )
            root_requirements.update(resolved_dist.direct_requirements)
            resolved_dist_by_file_artifact[file_artifact] = resolved_dist
        locked_resolve = LockedResolve(
            locked_requirements=SortedTuple(locked_requirements),
            platform_tag=PythonInterpreter.get().platform.tag,
        )  # type: LockedResolve

        resolved_dists_subset = OrderedSet()  # type: OrderedSet[ResolvedDistribution]
        for target in unique_targets:
            resolved = try_(
                locked_resolve.resolve(
                    target=target,
                    requirements=root_requirements,
                    constraints=[
                        constraint.requirement
                        for constraint in requirement_configuration.parse_constraints(
                            pip_configuration.network_configuration
                        )
                    ],
                    transitive=True,
                    build_configuration=pip_configuration.build_configuration,
                    include_all_matches=False,
                    dependency_configuration=dependency_configuration,
                )
            )
            for artifact in resolved.downloadable_artifacts:
                resolved_dists_subset.add(resolved_dist_by_file_artifact[artifact.artifact])

    return ResolveResult(
        dependency_configuration=dependency_configuration,
        distributions=tuple(resolved_dists_subset),
        type=result_type,
    )
