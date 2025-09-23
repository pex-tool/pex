# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import functools
import hashlib
import itertools
import os
from collections import defaultdict, deque

from pex import pex_warnings
from pex.atomic_directory import atomic_directory
from pex.cache.dirs import CacheDir, InstalledWheelDir
from pex.common import safe_relative_symlink
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import (
    Distribution,
    DistributionType,
    MetadataType,
    Requirement,
    find_distribution,
)
from pex.exceptions import production_assert, reportable_unexpected_error_msg
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.jobs import DEFAULT_MAX_JOBS, iter_map_parallel
from pex.orderedset import OrderedSet
from pex.pep_376 import InstalledWheel
from pex.pep_427 import InstallableType, InstallableWheel, InstallPaths, install_wheel_chroot
from pex.pep_503 import ProjectName
from pex.pip.version import PipVersion
from pex.requirements import LocalProjectRequirement
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolve.resolvers import ResolvedDistribution, Resolver, ResolveResult
from pex.result import Error
from pex.targets import LocalInterpreter, Target, Targets
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from pex.wheel import Wheel

if TYPE_CHECKING:
    from typing import DefaultDict, Deque, Iterable, Iterator, List, Set, Tuple, Union

    import attr  # vendor:skip
else:
    import pex.third_party.attr as attr


def _install_distribution(
    venv_install_paths,  # type: InstallPaths
    distribution,  # type: Distribution
):
    # type: (...) -> InstalledWheel

    production_assert(distribution.type is DistributionType.INSTALLED)
    production_assert(distribution.metadata.files.metadata.type is MetadataType.DIST_INFO)

    wheel = InstallableWheel(
        wheel=Wheel.from_distribution(distribution), install_paths=venv_install_paths
    )
    record_data = wheel.metadata_files.read("RECORD")
    if not record_data:
        raise AssertionError(
            reportable_unexpected_error_msg(
                "Distribution for {project_name} {version} installed at {location} "
                "unexpectedly has no installation RECORD.",
                project_name=distribution.project_name,
                version=distribution.version,
                location=distribution.location,
            )
        )

    installed_wheel_dir = InstalledWheelDir.create(
        wheel_name=wheel.wheel_file_name, install_hash=hashlib.sha256(record_data).hexdigest()
    )
    with atomic_directory(target_dir=installed_wheel_dir) as atomic_dir:
        if not atomic_dir.is_finalized():
            installed_wheel = install_wheel_chroot(
                wheel,
                atomic_dir.work_dir,
            )
            if not installed_wheel.fingerprint:
                raise AssertionError(reportable_unexpected_error_msg())
            runtime_key_dir = CacheDir.INSTALLED_WHEELS.path(installed_wheel.fingerprint)
            with atomic_directory(runtime_key_dir) as symlink_atomic_dir:
                if not atomic_dir.is_finalized():
                    # Note: Create a relative path symlink between the two directories so that the
                    # PEX_ROOT can be used within a chroot environment where the prefix of the path
                    # may change between programs running inside and outside the chroot.
                    safe_relative_symlink(
                        installed_wheel_dir,
                        os.path.join(symlink_atomic_dir.work_dir, wheel.wheel_file_name),
                    )
    return InstalledWheel.load(installed_wheel_dir)


def _install_venv_distributions(
    venv,  # type: Virtualenv
    distributions,  # type: Iterable[Distribution]
    compile=False,  # type: bool
    ignore_errors=False,  # type: bool
    max_install_jobs=DEFAULT_MAX_JOBS,  # type: int
):
    # type: (...) -> Iterator[FingerprintedDistribution]

    venv_install_paths = InstallPaths.interpreter(venv.interpreter)
    for installed_wheel in iter_map_parallel(
        inputs=distributions,
        function=functools.partial(_install_distribution, venv_install_paths),
        max_jobs=max_install_jobs,
    ):
        if not installed_wheel.fingerprint:
            raise AssertionError(reportable_unexpected_error_msg())
        yield FingerprintedDistribution(
            distribution=Distribution.load(installed_wheel.prefix_dir),
            fingerprint=installed_wheel.fingerprint,
        )


def _resolve_distributions(
    resolver,  # type: Resolver
    target,  # type: Target
    search_path,  # type: Iterable[str]
    requirements,  # type: Iterable[Requirement]
    allow_prereleases=False,  # type: bool
    compile=False,  # type: bool
    ignore_errors=False,  # type: bool
):
    # type: (...) -> Iterator[Union[Distribution, FingerprintedDistribution, Error]]

    to_resolve = deque(
        OrderedSet((requirement, ()) for requirement in requirements)
    )  # type: Deque[Tuple[Requirement, Iterable[str]]]
    resolved = set()  # type: Set[ProjectName]
    while to_resolve:
        requirement, extras = to_resolve.popleft()
        if requirement.project_name in resolved:
            continue

        if not target.requirement_applies(requirement, extras=extras):
            continue

        distribution = find_distribution(requirement.project_name, search_path)
        if not distribution:
            # TODO: XXX
            yield Error("TODO: XXX")
        elif requirement.contains(distribution, prereleases=allow_prereleases):
            production_assert(distribution.type is DistributionType.INSTALLED)
            if distribution.metadata.files.metadata.type is not MetadataType.DIST_INFO:
                result = resolver.resolve_requirements(
                    requirements=[str(distribution.as_requirement())],
                    targets=Targets.from_target(target),
                    transitive=False,
                )
                resolved.add(requirement.project_name)
                for dist in result.distributions:
                    if not target.wheel_applies(dist.distribution):
                        # TODO: XXX
                        yield Error("TODO: XXX")
                    to_resolve.extend(
                        (dep, requirement.extras)
                        for dep in dist.distribution.metadata.requires_dists
                    )
                    yield dist.fingerprinted_distribution
                continue
            if not target.wheel_applies(distribution):
                # TODO: XXX
                yield Error("TODO: XXX")

            resolved.add(requirement.project_name)
            to_resolve.extend(
                (dep, requirement.extras) for dep in distribution.metadata.requires_dists
            )
            yield distribution
        else:
            # TODO: XXX
            yield Error("TODO: XXX")


def resolve_from_venv(
    targets,  # type: Targets
    venv,  # type: Virtualenv
    requirement_configuration=RequirementConfiguration(),  # type: RequirementConfiguration
    pip_configuration=PipConfiguration(),  # type: PipConfiguration
    compile=False,  # type: bool
    ignore_errors=False,  # type: bool
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> Union[ResolveResult, Error]

    # TODO: XXX: How to handle targets?
    target = LocalInterpreter.create(venv.interpreter)

    # TODO: XXX: Mabe mix DEFAULT in here and che
    compatible_pip_version = (
        pip_configuration.version
        if pip_configuration.version and pip_configuration.version.requires_python_applies(target)
        else PipVersion.latest_compatible(target)
    )
    if pip_configuration.version and pip_configuration.version != compatible_pip_version:
        # TODO: XXX: Or just warn we changed the version to match the venv?
        pex_warnings.warn(
            "Adjusted Pip version from {version} to {compatible_version} to work with the venv "
            "interpreter.".format(
                version=pip_configuration.version, compatible_version=compatible_pip_version
            )
        )

    if result_type is InstallableType.WHEEL_FILE:
        # TODO: XXX: Reference an issue to chime in on?
        return Error(
            "Cannot resolve .whl files from virtual environment at {venv_dir}; Pex does not "
            "currently know how to turn an installed wheel back into a zipped wheel.".format(
                venv_dir=venv.venv_dir
            )
        )

    resolver = ConfiguredResolver(
        pip_configuration=attr.evolve(pip_configuration, version=compatible_pip_version)
    )
    fingerprinted_distributions = []  # type: List[FingerprintedDistribution]
    venv_distributions = []  # type: List[Distribution]
    direct_requirements_by_project_name = defaultdict(
        OrderedSet
    )  # type: DefaultDict[ProjectName, OrderedSet[Requirement]]
    if requirement_configuration.has_requirements:
        parsed_requirements = requirement_configuration.parse_requirements(
            network_configuration=pip_configuration.network_configuration
        )
        local_project_requirements = OrderedSet()  # type: OrderedSet[LocalProjectRequirement]
        root_requirements = OrderedSet()  # type: OrderedSet[Requirement]
        for parsed_requirement in parsed_requirements:
            if isinstance(parsed_requirement, LocalProjectRequirement):
                local_project_requirements.add(parsed_requirement)
            else:
                root_requirements.add(parsed_requirement.requirement)
                direct_requirements_by_project_name[
                    parsed_requirement.requirement.project_name
                ].add(parsed_requirement.requirement)

        if local_project_requirements:
            # TODO: XXX
            return Error("TODO: XXX")

        if requirement_configuration.constraint_files:
            # TODO: XXX
            pex_warnings.warn("TODO: XXX")

        for distribution_or_error in _resolve_distributions(
            resolver=resolver,
            target=target,
            search_path=tuple(
                site_packages_dir.path for site_packages_dir in venv.interpreter.site_packages
            ),
            requirements=root_requirements,
            allow_prereleases=pip_configuration.allow_prereleases,
            compile=compile,
            ignore_errors=ignore_errors,
        ):
            if isinstance(distribution_or_error, Error):
                return distribution_or_error
            elif isinstance(distribution_or_error, FingerprintedDistribution):
                fingerprinted_distributions.append(distribution_or_error)
            else:
                venv_distributions.append(distribution_or_error)
    else:
        sdists_to_resolve = []
        for venv_distribution in venv.iter_distributions():
            if venv_distribution.metadata.files.metadata.type is not MetadataType.DIST_INFO:
                sdists_to_resolve.append(str(venv_distribution.as_requirement()))
            else:
                venv_distributions.append(venv_distribution)
            direct_requirements_by_project_name[venv_distribution.metadata.project_name].add(
                venv_distribution.as_requirement()
            )
        result = resolver.resolve_requirements(
            sdists_to_resolve, targets=Targets.from_target(target), transitive=False
        )
        fingerprinted_distributions.extend(
            dist.fingerprinted_distribution for dist in result.distributions
        )

    return ResolveResult(
        dependency_configuration=dependency_configuration,
        distributions=tuple(
            ResolvedDistribution(
                target=target,
                fingerprinted_distribution=fingerprinted_distribution,
                direct_requirements=direct_requirements_by_project_name[
                    fingerprinted_distribution.project_name
                ],
            )
            for fingerprinted_distribution in itertools.chain(
                list(
                    _install_venv_distributions(
                        venv=venv,
                        distributions=venv_distributions,
                        compile=compile,
                        ignore_errors=ignore_errors,
                        max_install_jobs=pip_configuration.max_jobs,
                    )
                ),
                fingerprinted_distributions,
            )
        ),
        type=result_type,
    )
