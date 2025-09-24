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
    Constraint,
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
    from typing import DefaultDict, Deque, FrozenSet, Iterable, Iterator, List, Mapping, Set, Union

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


@attr.s(frozen=True)
class ResolveRequirement(object):
    requirement = attr.ib()  # type: Requirement
    activated_extras = attr.ib(default=frozenset())  # type: FrozenSet[str]
    required_by = attr.ib(default=None)  # type: ResolveRequirement

    @property
    def project_name(self):
        # type: () -> ProjectName
        return self.requirement.project_name

    def applies(
        self,
        target,  # type: Target
        dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
    ):
        # type: (...) -> bool

        if dependency_configuration.excluded_by(self.requirement):
            return False

        return target.requirement_applies(
            requirement=self.requirement, extras=self.activated_extras
        )

    def contains(
        self,
        distribution,  # type: Distribution
        prereleases=False,  # type: bool
    ):
        # type: (...) -> bool
        return self.requirement.contains(distribution, prereleases=prereleases)

    def dependency(
        self,
        requirement,  # type: Requirement
        target,  # type: Target
        dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
    ):
        # type: (...) -> ResolveRequirement
        return ResolveRequirement(
            requirement=dependency_configuration.overridden_by(requirement, target) or requirement,
            activated_extras=self.requirement.extras,
            required_by=self,
        )

    def __str__(self):
        # type: () -> str

        if not self.required_by:
            return "top level requirement {requirement}".format(requirement=self.requirement)

        return "{required_by} -> {requirement}".format(
            required_by=self.required_by, requirement=self.requirement
        )


def _resolve_distributions(
    venv,  # type: Virtualenv
    resolver,  # type: Resolver
    target,  # type: Target
    search_path,  # type: Iterable[str]
    requirements,  # type: Iterable[Requirement]
    constraints_by_project_name,  # type: Mapping[ProjectName, Iterable[Constraint]]
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
    allow_prereleases=False,  # type: bool
    compile=False,  # type: bool
    ignore_errors=False,  # type: bool
):
    # type: (...) -> Iterator[Union[Distribution, FingerprintedDistribution, Error]]

    def meets_requirement(
        selected_distribution,  # type: Distribution
        requirement,  # type: ResolveRequirement
    ):
        # type: (...) -> bool

        if not requirement.contains(selected_distribution, prereleases=allow_prereleases):
            return False

        constraints = [
            constraint
            for constraint in constraints_by_project_name[
                selected_distribution.metadata.project_name
            ]
            if target.requirement_applies(constraint, extras=requirement.activated_extras)
        ]
        if not constraints:
            return True

        return all(
            constraint.contains(selected_distribution, prereleases=allow_prereleases)
            for constraint in constraints
        )

    def error(message):
        # type: (str) -> Error
        return Error(
            "Resolve from venv at {venv} failed: {message}".format(
                venv=venv.venv_dir, message=message
            )
        )

    to_resolve = deque(
        OrderedSet(ResolveRequirement(requirement) for requirement in requirements)
    )  # type: Deque[ResolveRequirement]
    resolved = set()  # type: Set[ProjectName]
    while to_resolve:
        requirement = to_resolve.popleft()
        if requirement.project_name in resolved:
            continue

        if not requirement.applies(target, dependency_configuration):
            continue

        distribution = find_distribution(requirement.project_name, search_path)
        if not distribution:
            yield error(
                "The virtual environment does not have {project_name} installed but it is required "
                "by {requirement}".format(
                    project_name=requirement.project_name, requirement=requirement
                )
            )
        elif meets_requirement(distribution, requirement):
            production_assert(distribution.type is DistributionType.INSTALLED)
            resolved.add(requirement.project_name)
            if distribution.metadata.files.metadata.type is MetadataType.DIST_INFO:
                to_resolve.extend(
                    requirement.dependency(
                        requirement=dependency,
                        target=target,
                        dependency_configuration=dependency_configuration,
                    )
                    for dependency in distribution.metadata.requires_dists
                )
                yield distribution
            else:
                result = resolver.resolve_requirements(
                    requirements=[str(distribution.as_requirement())],
                    targets=Targets.from_target(target),
                    transitive=False,
                    compile=compile,
                    ignore_errors=ignore_errors,
                )
                for dist in result.distributions:
                    to_resolve.extend(
                        requirement.dependency(
                            requirement=dependency,
                            target=target,
                            dependency_configuration=dependency_configuration,
                        )
                        for dependency in dist.distribution.metadata.requires_dists
                    )
                    yield dist.fingerprinted_distribution
        else:
            yield error(
                "The virtual environment has {project_name} {version} installed but it does not "
                "meet {requirement}{suffix}.".format(
                    project_name=distribution.project_name,
                    version=distribution.version,
                    requirement=requirement,
                    suffix=(
                        " due to supplied constraints"
                        if requirement.contains(distribution, prereleases=allow_prereleases)
                        else ""
                    ),
                )
            )


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

    if result_type is InstallableType.WHEEL_FILE:
        return Error(
            "Cannot resolve .whl files from virtual environment at {venv_dir}; its distributions "
            "are all installed.".format(venv_dir=venv.venv_dir)
        )

    target = LocalInterpreter.create(venv.interpreter)
    if not targets.is_empty:
        return Error(
            "You configured custom targets via --python, --interpreter-constraint, --platform or "
            "--complete-platform but custom targets are not allowed when resolving from a virtual "
            "environment.\n"
            "For such resolves, the supported target is implicitly the one matching the venv "
            "interpreter; in this case: {target}.".format(target=target.render_description())
        )

    if pip_configuration.version:
        compatible_pip_version = (
            pip_configuration.version
            if pip_configuration.version.requires_python_applies(target)
            else PipVersion.latest_compatible(target)
        )
        if pip_configuration.version != compatible_pip_version:
            if pip_configuration.allow_version_fallback:
                pex_warnings.warn(
                    "Adjusted Pip version from {version} to {compatible_version} to work with the "
                    "venv interpreter.".format(
                        version=pip_configuration.version, compatible_version=compatible_pip_version
                    )
                )
            else:
                return Error(
                    "Pip version {version} is not compatible with the Python {python_version} "
                    "venv interpreter.".format(
                        version=pip_configuration.version, python_version=venv.interpreter.python
                    )
                )
    elif PipVersion.DEFAULT.requires_python_applies(target):
        compatible_pip_version = PipVersion.DEFAULT
    else:
        compatible_pip_version = PipVersion.latest_compatible(target)

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
            return Error(
                "Local project directory requirements cannot be resolved from venvs.\n"
                "Use the project name instead if it is installed in the venv."
            )

        constraints_by_project_name = defaultdict(
            OrderedSet
        )  # type: DefaultDict[ProjectName, OrderedSet[Constraint]]
        for constraint in requirement_configuration.parse_constraints(
            network_configuration=pip_configuration.network_configuration
        ):
            constraints_by_project_name[constraint.project_name].add(constraint.requirement)

        for distribution_or_error in _resolve_distributions(
            venv=venv,
            resolver=resolver,
            target=target,
            search_path=tuple(
                site_packages_dir.path for site_packages_dir in venv.interpreter.site_packages
            ),
            requirements=root_requirements,
            constraints_by_project_name=constraints_by_project_name,
            dependency_configuration=dependency_configuration,
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
            sdists_to_resolve,
            constraint_files=requirement_configuration.constraint_files,
            targets=Targets.from_target(target),
            transitive=False,
            compile=compile,
            ignore_errors=ignore_errors,
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
                        max_install_jobs=pip_configuration.max_jobs,
                    )
                ),
                fingerprinted_distributions,
            )
        ),
        type=result_type,
    )
