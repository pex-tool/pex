# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import functools
import hashlib
import os
from collections import defaultdict, deque

from pex import pex_warnings
from pex.atomic_directory import atomic_directory
from pex.cache.dirs import CacheDir, InstalledWheelDir
from pex.common import pluralize, safe_relative_symlink
from pex.compatibility import commonpath
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
from pex.installed_wheel import InstalledWheel
from pex.jobs import DEFAULT_MAX_JOBS, iter_map_parallel
from pex.orderedset import OrderedSet
from pex.pep_376 import Record
from pex.pep_427 import InstallableType, InstallableWheel, InstallPaths, install_wheel_chroot
from pex.pep_503 import ProjectName
from pex.pip.version import PipVersion
from pex.requirements import LocalProjectRequirement
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolve.resolvers import ResolvedDistribution, Resolver, ResolveResult
from pex.result import Error
from pex.sysconfig import script_name
from pex.targets import LocalInterpreter, Target, Targets
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from pex.wheel import WHEEL, Wheel
from pex.whl import repacked_whl

if TYPE_CHECKING:
    from typing import (
        DefaultDict,
        Deque,
        FrozenSet,
        Iterable,
        Iterator,
        List,
        Mapping,
        Set,
        Tuple,
        Union,
    )

    import attr  # vendor:skip
else:
    import pex.third_party.attr as attr


def _normalize_record(
    distribution,  # type: Distribution
    install_paths,  # type: InstallPaths
    record_data,  # type: bytes
):
    # type: (...) -> bytes

    entry_map = distribution.get_entry_map()
    entry_point_scripts = {
        script_name(entry_point)
        for key in ("console_scripts", "gui_scripts")
        for entry_point in entry_map.get(key, {})
    }
    if not entry_point_scripts:
        return record_data

    scripts_dir = os.path.realpath(install_paths.scripts)
    record_lines = record_data.decode("utf-8").splitlines(True)  # N.B. no kw in 2.7: keepends=True
    eol = os.sep
    if record_lines:
        eol = "\r\n" if record_lines[0].endswith("\r\n") else "\n"

    installed_files = [
        installed_file
        for installed_file in Record.read(lines=iter(record_lines))
        if (
            (os.path.basename(installed_file.path) not in entry_point_scripts)
            or (
                scripts_dir
                != commonpath(
                    (
                        scripts_dir,
                        os.path.realpath(os.path.join(distribution.location, installed_file.path)),
                    )
                )
            )
        )
    ]
    return Record.write_bytes(installed_files=installed_files, eol=eol)


def _install_distribution(
    venv_distribution,  # type: VenvDistribution
    result_type,  # type: InstallableType.Value
    use_system_time,  # type: bool
):
    # type: (...) -> ResolvedDistribution

    interpreter = venv_distribution.target.interpreter
    distribution = venv_distribution.distribution

    production_assert(distribution.type is DistributionType.INSTALLED)
    production_assert(distribution.metadata.files.metadata.type is MetadataType.DIST_INFO)

    venv_install_paths = InstallPaths.interpreter(
        interpreter,
        project_name=distribution.metadata.project_name,
        root_is_purelib=WHEEL.from_distribution(distribution).root_is_purelib,
    )
    wheel = InstallableWheel.from_whl(
        whl=Wheel.from_distribution(distribution), install_paths=venv_install_paths
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
        wheel_name=wheel.wheel_file_name,
        install_hash=hashlib.sha256(
            _normalize_record(
                distribution=Distribution(location=wheel.location, metadata=wheel.dist_metadata()),
                install_paths=venv_install_paths,
                record_data=record_data,
            )
        ).hexdigest(),
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
                if not symlink_atomic_dir.is_finalized():
                    # Note: Create a relative path symlink between the two directories so that the
                    # PEX_ROOT can be used within a chroot environment where the prefix of the path
                    # may change between programs running inside and outside the chroot.
                    safe_relative_symlink(
                        installed_wheel_dir,
                        os.path.join(symlink_atomic_dir.work_dir, wheel.wheel_file_name),
                    )

    installed_wheel = InstalledWheel.load(installed_wheel_dir)
    if not installed_wheel.fingerprint:
        raise AssertionError(reportable_unexpected_error_msg())

    if result_type is InstallableType.INSTALLED_WHEEL_CHROOT:
        return ResolvedDistribution(
            target=venv_distribution.target,
            fingerprinted_distribution=FingerprintedDistribution(
                distribution=Distribution.load(installed_wheel.prefix_dir),
                fingerprint=installed_wheel.fingerprint,
            ),
            direct_requirements=venv_distribution.direct_requirements,
        )

    return ResolvedDistribution(
        target=venv_distribution.target,
        fingerprinted_distribution=repacked_whl(
            installed_wheel,
            fingerprint=installed_wheel.fingerprint,
            use_system_time=use_system_time,
        ),
        direct_requirements=venv_distribution.direct_requirements,
    )


@attr.s(frozen=True)
class VenvDistribution(object):
    target = attr.ib()  # type: LocalInterpreter
    distribution = attr.ib()  # type: Distribution
    direct_requirements = attr.ib()  # type: Iterable[Requirement]


def _install_venv_distributions(
    venv_resolve_results,  # type: Iterable[VenvResolveResult]
    max_install_jobs=DEFAULT_MAX_JOBS,  # type: int
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
    use_system_time=False,  # type: bool
):
    # type: (...) -> Iterator[ResolvedDistribution]

    seen = set()  # type: Set[str]

    venv_distributions = []  # type: List[VenvDistribution]
    for venv_resolve_result in venv_resolve_results:
        target = venv_resolve_result.target
        direct_requirements = venv_resolve_result.direct_requirements_by_project_name
        for re_resolved_distribution in venv_resolve_result.re_resolved_distributions:
            wheel_file_name = Wheel.from_distribution(
                re_resolved_distribution.distribution
            ).wheel_file_name
            if wheel_file_name in seen:
                continue

            seen.add(wheel_file_name)
            yield ResolvedDistribution(
                target=target,
                fingerprinted_distribution=re_resolved_distribution,
                direct_requirements=direct_requirements.get(
                    re_resolved_distribution.project_name, ()
                ),
            )
        for venv_distribution in venv_resolve_result.venv_distributions:
            wheel_file_name = Wheel.from_distribution(venv_distribution).wheel_file_name
            if wheel_file_name in seen:
                continue

            seen.add(wheel_file_name)
            venv_distributions.append(
                VenvDistribution(
                    target=target,
                    distribution=venv_distribution,
                    direct_requirements=direct_requirements.get(
                        venv_distribution.metadata.project_name, ()
                    ),
                )
            )

    for resolved_distribution in iter_map_parallel(
        inputs=venv_distributions,
        function=functools.partial(
            _install_distribution, result_type=result_type, use_system_time=use_system_time
        ),
        max_jobs=max_install_jobs,
    ):
        yield resolved_distribution


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
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
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
            editable_project_url = distribution.editable_install_url()
            if (
                not editable_project_url
                and distribution.metadata.files.metadata.type is MetadataType.DIST_INFO
            ):
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
                source_requirement = (
                    "{project} @ {url}".format(
                        project=distribution.metadata.project_name, url=editable_project_url
                    )
                    if editable_project_url
                    else str(distribution.as_requirement())
                )
                result = resolver.resolve_requirements(
                    requirements=[source_requirement],
                    targets=Targets.from_target(target),
                    transitive=False,
                    compile=compile,
                    ignore_errors=ignore_errors,
                    result_type=result_type,
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


@attr.s(frozen=True)
class VenvResolveResult(object):
    venv = attr.ib()  # type: Virtualenv
    venv_distributions = attr.ib()  # type: Tuple[Distribution, ...]
    re_resolved_distributions = attr.ib()  # type: Tuple[FingerprintedDistribution, ...]
    direct_requirements_by_project_name = attr.ib(
        eq=False
    )  # type: Mapping[ProjectName, Iterable[Requirement]]

    @property
    def target(self):
        # type: () -> LocalInterpreter
        return LocalInterpreter.create(self.venv.interpreter)


def _resolve_from_venv(
    venv,  # type: Virtualenv
    requirement_configuration,  # type: RequirementConfiguration
    pip_configuration,  # type: PipConfiguration
    compile,  # type: bool
    ignore_errors,  # type: bool
    result_type,  # type: InstallableType.Value
    dependency_configuration,  # type: DependencyConfiguration
):
    # type: (...) -> Union[VenvResolveResult, Error]
    target = LocalInterpreter.create(venv.interpreter)

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
            result_type=result_type,
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
                editable_project_url = venv_distribution.editable_install_url()
                if editable_project_url:
                    sdists_to_resolve.append(
                        "{project_name} @ {url}".format(
                            project_name=venv_distribution.metadata.project_name,
                            url=editable_project_url,
                        )
                    )
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

    return VenvResolveResult(
        venv=venv,
        venv_distributions=tuple(venv_distributions),
        re_resolved_distributions=tuple(fingerprinted_distributions),
        direct_requirements_by_project_name=direct_requirements_by_project_name,
    )


def resolve_from_venvs(
    targets,  # type: Targets
    venvs,  # type: Tuple[Virtualenv, ...]
    requirement_configuration=RequirementConfiguration(),  # type: RequirementConfiguration
    pip_configuration=PipConfiguration(),  # type: PipConfiguration
    compile=False,  # type: bool
    ignore_errors=False,  # type: bool
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> Union[ResolveResult, Error]

    if not targets.is_empty:
        return Error(
            "You configured custom targets via --python, --interpreter-constraint, --platform or "
            "--complete-platform but custom targets are not allowed when resolving from {venvs}.\n"
            "For such resolves, the supported target is implicitly the one matching the venv "
            "{interpreters}; in this case:{targets}.".format(
                venvs="a virtual environment" if len(venvs) == 1 else "virtual environments",
                interpreters=pluralize(venvs, "interpreter"),
                targets=(
                    " {target}".format(
                        target=LocalInterpreter.create(venvs[0].interpreter).render_description()
                    )
                    if len(venvs) == 1
                    else "\n  {targets}".format(
                        targets="\n  ".join(
                            LocalInterpreter.create(venv.interpreter).render_description()
                            for venv in venvs
                        )
                    )
                ),
            )
        )

    errors = []  # type: List[Error]
    venv_resolve_results = []  # type: List[VenvResolveResult]
    for result in iter_map_parallel(
        venvs,
        functools.partial(
            _resolve_from_venv,
            requirement_configuration=requirement_configuration,
            pip_configuration=pip_configuration,
            compile=compile,
            ignore_errors=ignore_errors,
            result_type=result_type,
            dependency_configuration=dependency_configuration,
        ),
    ):
        if isinstance(result, Error):
            errors.append(result)
        else:
            venv_resolve_results.append(result)

    if len(errors) == 1:
        return errors[0]
    elif errors:
        return Error(
            "Failed to resolve from {count} of {total} virtual environments:\n{failures}".format(
                count=len(errors),
                total=len(venvs),
                failures="\n".join(
                    "{index}. {error}".format(index=index, error=error)
                    for index, error in enumerate(errors, start=1)
                ),
            )
        )

    return ResolveResult(
        dependency_configuration=dependency_configuration,
        distributions=tuple(
            _install_venv_distributions(
                venv_resolve_results,
                max_install_jobs=pip_configuration.max_jobs,
                result_type=result_type,
                use_system_time=True,
            )
        ),
        type=result_type,
    )
