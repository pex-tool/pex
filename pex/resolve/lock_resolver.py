# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from collections import defaultdict

from pex.auth import PasswordDatabase, PasswordEntry
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import Requirement, is_wheel
from pex.exceptions import production_assert
from pex.network_configuration import NetworkConfiguration
from pex.pep_427 import InstallableType
from pex.pep_503 import ProjectName
from pex.pip.tool import PackageIndexConfiguration
from pex.pip.version import PipVersionValue
from pex.resolve.lock_downloader import LockDownloader
from pex.resolve.locked_resolve import (
    DownloadableArtifact,
    LocalProjectArtifact,
    LockConfiguration,
    LockStyle,
    UnFingerprintedLocalProjectArtifact,
)
from pex.resolve.lockfile.download_manager import DownloadedArtifact
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.lockfile.pep_751 import Package, Pylock
from pex.resolve.lockfile.pep_751 import subset as subset_pylock
from pex.resolve.lockfile.subset import SubsetResult
from pex.resolve.lockfile.subset import subset as subset_pex_lock
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import BuildConfiguration, ResolverVersion
from pex.resolve.resolvers import ResolvedDistribution, Resolver, ResolveResult
from pex.resolver import BuildAndInstallRequest, BuildRequest, InstallRequest
from pex.result import Error, try_
from pex.targets import Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import (
        DefaultDict,
        Dict,
        FrozenSet,
        Iterable,
        List,
        Optional,
        Sequence,
        Set,
        Tuple,
        Union,
    )


def _check_subset(
    pylock,  # type: Pylock
    transitive,  # type: bool
    target,  # type: Target
    packages,  # type: Sequence[Package]
    resolved_distributions,  # type: Sequence[ResolvedDistribution]
):
    # type: (...) -> Optional[Error]

    expected_resolve = {package.project_name for package in packages}

    actual_resolve = set()  # type: Set[ProjectName]
    for resolved_distribution in resolved_distributions:
        actual_resolve.add(resolved_distribution.distribution.metadata.project_name)
        if transitive:
            extras = frozenset(
                extra
                for direct_requirement in resolved_distribution.direct_requirements
                for extra in direct_requirement.extras
            )
            for req in resolved_distribution.distribution.metadata.requires_dists:
                if target.requirement_applies(req, extras=extras):
                    actual_resolve.add(req.project_name)

    if expected_resolve == actual_resolve:
        return None

    needed = actual_resolve - expected_resolve
    mismatch_msg = (
        "The following projects were resolved:\n"
        "+ {expected}\n"
        "\n"
        "These additional dependencies need to be resolved (as well as any transitive "
        "dependencies they may have):\n"
        "+ {needed}".format(
            expected="\n+ ".join(sorted(map(str, expected_resolve))),
            needed="\n+ ".join(sorted(map(str, needed))),
        )
    )
    production_assert(
        pylock.created_by != "pex",
        "{mismatch_msg}\n" "\n" "This indicates a bug in Pex PEP-751 support.",
        mismatch_msg,
    )
    return Error(
        "{mismatch_msg}\n"
        "\n"
        "The lock {lock_desc} likely does not include optional `dependencies` metadata for its "
        "packages.\n"
        "This metadata is required for Pex to subset a PEP-751 lock.".format(
            mismatch_msg=mismatch_msg, lock_desc=pylock.render_description()
        )
    )


def resolve_from_pylock(
    targets,  # type: Targets
    pylock,  # type: Pylock
    resolver,  # type: Resolver
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    extras=frozenset(),  # type: FrozenSet[str]
    dependency_groups=frozenset(),  # type: FrozenSet[str]
    constraint_files=None,  # type: Optional[Iterable[str]]
    indexes=None,  # type: Optional[Sequence[str]]
    find_links=None,  # type: Optional[Sequence[str]]
    resolver_version=None,  # type: Optional[ResolverVersion.Value]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    password_entries=(),  # type: Iterable[PasswordEntry]
    build_configuration=BuildConfiguration(),  # type: BuildConfiguration
    compile=False,  # type: bool
    transitive=True,  # type: bool
    verify_wheels=True,  # type: bool
    max_parallel_jobs=None,  # type: Optional[int]
    pip_version=None,  # type: Optional[PipVersionValue]
    use_pip_config=False,  # type: bool
    extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
    keyring_provider=None,  # type: Optional[str]
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> Union[ResolveResult, Error]

    requirement_configuration = RequirementConfiguration(
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
    )
    pylock_subset_result = try_(
        subset_pylock(
            targets=targets,
            pylock=pylock,
            requirement_configuration=requirement_configuration,
            extras=extras,
            dependency_groups=dependency_groups,
            network_configuration=network_configuration,
            build_configuration=build_configuration,
            transitive=transitive,
            dependency_configuration=dependency_configuration,
        )
    )
    resolve_result = _resolve_from_subset_result(
        pylock_subset_result.subset_result,
        # This ensures artifact downloads via Pip will not be rejected by Pip for mismatched
        # target interpreters, etc.
        lock_configuration=LockConfiguration(
            style=LockStyle.UNIVERSAL,
            requires_python=tuple([pylock.requires_python]) if pylock.requires_python else (),
        ),
        resolver=resolver,
        indexes=indexes,
        find_links=find_links,
        resolver_version=resolver_version,
        network_configuration=network_configuration,
        password_entries=password_entries,
        build_configuration=build_configuration,
        compile=compile,
        verify_wheels=verify_wheels,
        max_parallel_jobs=max_parallel_jobs,
        pip_version=pip_version,
        use_pip_config=use_pip_config,
        extra_pip_requirements=extra_pip_requirements,
        keyring_provider=keyring_provider,
        result_type=result_type,
        dependency_configuration=dependency_configuration,
    )
    if not requirement_configuration.has_requirements or isinstance(resolve_result, Error):
        return resolve_result

    resolved_distributions_by_target = defaultdict(
        list
    )  # type: DefaultDict[Target, List[ResolvedDistribution]]
    for resolved_distribution in resolve_result.distributions:
        resolved_distributions_by_target[resolved_distribution.target].append(resolved_distribution)
    for target, packages in pylock_subset_result.packages_by_target.items():
        resolved_distributions = resolved_distributions_by_target[target]
        error = _check_subset(pylock, transitive, target, packages, resolved_distributions)
        if error:
            return error

    return resolve_result


def download_from_pylock(
    targets,  # type: Targets
    pylock,  # type: Pylock
    resolver,  # type: Resolver
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    extras=frozenset(),  # type: FrozenSet[str]
    dependency_groups=frozenset(),  # type: FrozenSet[str]
    constraint_files=None,  # type: Optional[Iterable[str]]
    indexes=None,  # type: Optional[Sequence[str]]
    find_links=None,  # type: Optional[Sequence[str]]
    resolver_version=None,  # type: Optional[ResolverVersion.Value]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    password_entries=(),  # type: Iterable[PasswordEntry]
    build_configuration=BuildConfiguration(),  # type: BuildConfiguration
    transitive=True,  # type: bool
    max_parallel_jobs=None,  # type: Optional[int]
    pip_version=None,  # type: Optional[PipVersionValue]
    use_pip_config=False,  # type: bool
    extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
    keyring_provider=None,  # type: Optional[str]
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> Union[Tuple[DownloadedArtifact, ...], Error]

    requirement_configuration = RequirementConfiguration(
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
    )
    pylock_subset_result = try_(
        subset_pylock(
            targets=targets,
            pylock=pylock,
            requirement_configuration=requirement_configuration,
            extras=extras,
            dependency_groups=dependency_groups,
            network_configuration=network_configuration,
            build_configuration=build_configuration,
            transitive=transitive,
            dependency_configuration=dependency_configuration,
        )
    )
    downloaded_artifacts = _download_from_subset_result(
        pylock_subset_result.subset_result,
        # This ensures artifact downloads via Pip will not be rejected by Pip for mismatched
        # target interpreters, etc.
        lock_configuration=LockConfiguration(
            style=LockStyle.UNIVERSAL,
            requires_python=tuple([pylock.requires_python]) if pylock.requires_python else (),
        ),
        resolver=resolver,
        indexes=indexes,
        find_links=find_links,
        resolver_version=resolver_version,
        network_configuration=network_configuration,
        password_entries=password_entries,
        build_configuration=build_configuration,
        max_parallel_jobs=max_parallel_jobs,
        pip_version=pip_version,
        use_pip_config=use_pip_config,
        extra_pip_requirements=extra_pip_requirements,
        keyring_provider=keyring_provider,
    )
    if isinstance(downloaded_artifacts, Error):
        return downloaded_artifacts
    return tuple(downloaded_artifacts.values())


def resolve_from_pex_lock(
    targets,  # type: Targets
    lock,  # type: Lockfile
    resolver,  # type: Resolver
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    constraint_files=None,  # type: Optional[Iterable[str]]
    indexes=None,  # type: Optional[Sequence[str]]
    find_links=None,  # type: Optional[Sequence[str]]
    resolver_version=None,  # type: Optional[ResolverVersion.Value]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    password_entries=(),  # type: Iterable[PasswordEntry]
    build_configuration=BuildConfiguration(),  # type: BuildConfiguration
    compile=False,  # type: bool
    transitive=True,  # type: bool
    verify_wheels=True,  # type: bool
    max_parallel_jobs=None,  # type: Optional[int]
    pip_version=None,  # type: Optional[PipVersionValue]
    use_pip_config=False,  # type: bool
    extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
    keyring_provider=None,  # type: Optional[str]
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> Union[ResolveResult, Error]

    dependency_configuration = lock.dependency_configuration().merge(dependency_configuration)
    subset_result = try_(
        subset_pex_lock(
            targets=targets,
            lock=lock,
            requirement_configuration=RequirementConfiguration(
                requirements=requirements,
                requirement_files=requirement_files,
                constraint_files=constraint_files,
            ),
            network_configuration=network_configuration,
            build_configuration=build_configuration,
            transitive=transitive,
            dependency_configuration=dependency_configuration,
        )
    )
    return _resolve_from_subset_result(
        subset_result,
        lock_configuration=lock.lock_configuration(),
        resolver=resolver,
        indexes=indexes,
        find_links=find_links,
        resolver_version=resolver_version,
        network_configuration=network_configuration,
        password_entries=password_entries,
        build_configuration=build_configuration,
        compile=compile,
        verify_wheels=verify_wheels,
        max_parallel_jobs=max_parallel_jobs,
        pip_version=pip_version,
        use_pip_config=use_pip_config,
        extra_pip_requirements=extra_pip_requirements,
        keyring_provider=keyring_provider,
        result_type=result_type,
        dependency_configuration=dependency_configuration,
    )


def download_from_pex_lock(
    targets,  # type: Targets
    lock,  # type: Lockfile
    resolver,  # type: Resolver
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    constraint_files=None,  # type: Optional[Iterable[str]]
    indexes=None,  # type: Optional[Sequence[str]]
    find_links=None,  # type: Optional[Sequence[str]]
    resolver_version=None,  # type: Optional[ResolverVersion.Value]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    password_entries=(),  # type: Iterable[PasswordEntry]
    build_configuration=BuildConfiguration(),  # type: BuildConfiguration
    transitive=True,  # type: bool
    max_parallel_jobs=None,  # type: Optional[int]
    pip_version=None,  # type: Optional[PipVersionValue]
    use_pip_config=False,  # type: bool
    extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
    keyring_provider=None,  # type: Optional[str]
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> Union[Tuple[DownloadedArtifact, ...], Error]

    dependency_configuration = lock.dependency_configuration().merge(dependency_configuration)
    subset_result = try_(
        subset_pex_lock(
            targets=targets,
            lock=lock,
            requirement_configuration=RequirementConfiguration(
                requirements=requirements,
                requirement_files=requirement_files,
                constraint_files=constraint_files,
            ),
            network_configuration=network_configuration,
            build_configuration=build_configuration,
            transitive=transitive,
            dependency_configuration=dependency_configuration,
        )
    )
    downloaded_artifacts = _download_from_subset_result(
        subset_result,
        lock_configuration=lock.lock_configuration(),
        resolver=resolver,
        indexes=indexes,
        find_links=find_links,
        resolver_version=resolver_version,
        network_configuration=network_configuration,
        password_entries=password_entries,
        build_configuration=build_configuration,
        max_parallel_jobs=max_parallel_jobs,
        pip_version=pip_version,
        use_pip_config=use_pip_config,
        extra_pip_requirements=extra_pip_requirements,
        keyring_provider=keyring_provider,
    )
    if isinstance(downloaded_artifacts, Error):
        return downloaded_artifacts
    return tuple(downloaded_artifacts.values())


def _download_from_subset_result(
    subset_result,  # type: SubsetResult
    lock_configuration,  # type: LockConfiguration
    resolver,  # type: Resolver
    indexes=None,  # type: Optional[Sequence[str]]
    find_links=None,  # type: Optional[Sequence[str]]
    resolver_version=None,  # type: Optional[ResolverVersion.Value]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    password_entries=(),  # type: Iterable[PasswordEntry]
    build_configuration=BuildConfiguration(),  # type: BuildConfiguration
    max_parallel_jobs=None,  # type: Optional[int]
    pip_version=None,  # type: Optional[PipVersionValue]
    use_pip_config=False,  # type: bool
    extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
    keyring_provider=None,  # type: Optional[str]
):
    # type: (...) -> Union[Dict[DownloadableArtifact, DownloadedArtifact], Error]

    downloadable_artifacts_and_targets = tuple(
        (downloadable_artifact, resolved_subset.target)
        for resolved_subset in subset_result.subsets
        for downloadable_artifact in resolved_subset.resolved.downloadable_artifacts
    )
    lock_downloader = LockDownloader.create(
        targets=tuple(resolved_subset.target for resolved_subset in subset_result.subsets),
        lock_configuration=lock_configuration,
        resolver=resolver,
        indexes=indexes,
        find_links=find_links,
        max_parallel_jobs=max_parallel_jobs,
        pip_version=pip_version,
        resolver_version=resolver_version,
        network_configuration=network_configuration,
        password_entries=password_entries,
        build_configuration=build_configuration,
        use_pip_config=use_pip_config,
        extra_pip_requirements=extra_pip_requirements,
        keyring_provider=keyring_provider,
    )
    with TRACER.timed(
        "Downloading {url_count} distributions to satisfy {requirement_count} requirements".format(
            url_count=len(downloadable_artifacts_and_targets),
            requirement_count=len(subset_result.requirements),
        )
    ):
        return lock_downloader.download_artifacts(downloadable_artifacts_and_targets)


def _resolve_from_subset_result(
    subset_result,  # type: SubsetResult
    lock_configuration,  # type: LockConfiguration
    resolver,  # type: Resolver
    indexes=None,  # type: Optional[Sequence[str]]
    find_links=None,  # type: Optional[Sequence[str]]
    resolver_version=None,  # type: Optional[ResolverVersion.Value]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    password_entries=(),  # type: Iterable[PasswordEntry]
    build_configuration=BuildConfiguration(),  # type: BuildConfiguration
    compile=False,  # type: bool
    verify_wheels=True,  # type: bool
    max_parallel_jobs=None,  # type: Optional[int]
    pip_version=None,  # type: Optional[PipVersionValue]
    use_pip_config=False,  # type: bool
    extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
    keyring_provider=None,  # type: Optional[str]
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> Union[ResolveResult, Error]

    downloaded_artifacts = _download_from_subset_result(
        subset_result,
        lock_configuration=lock_configuration,
        resolver=resolver,
        indexes=indexes,
        find_links=find_links,
        resolver_version=resolver_version,
        network_configuration=network_configuration,
        password_entries=password_entries,
        build_configuration=build_configuration,
        max_parallel_jobs=max_parallel_jobs,
        pip_version=pip_version,
        use_pip_config=use_pip_config,
        extra_pip_requirements=extra_pip_requirements,
        keyring_provider=keyring_provider,
    )
    if isinstance(downloaded_artifacts, Error):
        return downloaded_artifacts

    with TRACER.timed("Categorizing {} downloaded artifacts".format(len(downloaded_artifacts))):
        build_requests = []
        install_requests = []
        for resolved_subset in subset_result.subsets:
            for downloadable_artifact in resolved_subset.resolved.downloadable_artifacts:
                downloaded_artifact = downloaded_artifacts[downloadable_artifact]
                if is_wheel(downloaded_artifact.path):
                    install_requests.append(
                        InstallRequest(
                            target=resolved_subset.target,
                            wheel_path=downloaded_artifact.path,
                            fingerprint=downloaded_artifact.fingerprint,
                        )
                    )
                else:
                    build_requests.append(
                        BuildRequest(
                            target=resolved_subset.target,
                            source_path=downloaded_artifact.path,
                            fingerprint=downloaded_artifact.fingerprint,
                            subdirectory=downloaded_artifact.subdirectory,
                        )
                    )
    with TRACER.timed(
        "Building {} artifacts and installing {}".format(
            len(build_requests), len(build_requests) + len(install_requests)
        )
    ):
        build_and_install_request = BuildAndInstallRequest(
            build_requests=build_requests,
            install_requests=install_requests,
            direct_requirements=subset_result.requirements,
            package_index_configuration=PackageIndexConfiguration.create(
                pip_version=pip_version,
                resolver_version=resolver_version,
                indexes=indexes,
                find_links=find_links,
                network_configuration=network_configuration,
                password_entries=PasswordDatabase.from_netrc().append(password_entries).entries,
                use_pip_config=use_pip_config,
                extra_pip_requirements=extra_pip_requirements,
                keyring_provider=keyring_provider,
            ),
            compile=compile,
            build_configuration=build_configuration,
            verify_wheels=verify_wheels,
            pip_version=pip_version,
            resolver=resolver,
            dependency_configuration=dependency_configuration,
        )

        local_project_directory_to_sdist = {
            downloadable_artifact.artifact.directory: downloaded_artifact.path
            for downloadable_artifact, downloaded_artifact in downloaded_artifacts.items()
            if isinstance(
                downloadable_artifact.artifact,
                (LocalProjectArtifact, UnFingerprintedLocalProjectArtifact),
            )
        }

        # This otherwise checks that resolved distributions all meet internal requirement
        # constraints (This allows pip-legacy-resolver resolves with invalid solutions to be
        # failed post-facto by Pex at PEX build time). We've already done this via
        # `LockedResolve.resolve` above and need not waste time (~O(100ms)) doing this again.
        ignore_errors = True

        distributions = (
            build_and_install_request.install_distributions(
                ignore_errors=ignore_errors,
                max_parallel_jobs=max_parallel_jobs,
                local_project_directory_to_sdist=local_project_directory_to_sdist,
            )
            if result_type is InstallableType.INSTALLED_WHEEL_CHROOT
            else build_and_install_request.build_distributions(
                ignore_errors=ignore_errors,
                max_parallel_jobs=max_parallel_jobs,
                local_project_directory_to_sdist=local_project_directory_to_sdist,
            )
        )
    return ResolveResult(
        dependency_configuration=dependency_configuration,
        distributions=tuple(distributions),
        type=result_type,
    )
