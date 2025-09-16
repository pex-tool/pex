# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import shutil
from collections import OrderedDict, defaultdict
from multiprocessing.pool import ThreadPool

from pex import hashing
from pex.auth import PasswordDatabase
from pex.build_system import pep_517
from pex.common import pluralize, safe_mkdtemp
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import DistMetadata, ProjectNameAndVersion, Requirement
from pex.exceptions import production_assert
from pex.fetcher import URLFetcher
from pex.jobs import Job, Retain, SpawnedJob, execute_parallel
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pip.download_observer import DownloadObserver
from pex.pip.tool import PackageIndexConfiguration
from pex.pip.version import PipVersionValue
from pex.resolve import lock_resolver, locker, resolvers
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.downloads import ArtifactDownloader
from pex.resolve.lock_downloader import LockDownloader
from pex.resolve.locked_resolve import (
    Artifact,
    DownloadableArtifact,
    FileArtifact,
    LocalProjectArtifact,
    LockConfiguration,
    LockedResolve,
    LockStyle,
    VCSArtifact,
)
from pex.resolve.locker import Locker
from pex.resolve.lockfile.download_manager import DownloadManager
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.lockfile.targets import LockTargets
from pex.resolve.package_repository import ReposConfiguration
from pex.resolve.pep_691.fingerprint_service import FingerprintService
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolved_requirement import Pin, ResolvedRequirement
from pex.resolve.resolver_configuration import BuildConfiguration, PipConfiguration, ResolverVersion
from pex.resolve.resolvers import Resolver
from pex.resolver import BuildRequest, Downloaded, DownloadTarget, ResolveObserver, WheelBuilder
from pex.resolver import download as pip_download
from pex.result import Error, try_
from pex.targets import Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.variables import ENV, Variables
from pex.version import __version__

if TYPE_CHECKING:
    from typing import DefaultDict, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

    import attr  # vendor:skip

    from pex.hashing import HintedDigest
    from pex.requirements import ParsedRequirement

    AnyArtifact = Union[FileArtifact, LocalProjectArtifact, VCSArtifact]
else:
    from pex.third_party import attr


class CreateLockDownloadManager(DownloadManager[Artifact]):
    @classmethod
    def create(
        cls,
        download_dir,  # type: str
        locked_resolves,  # type: Iterable[LockedResolve]
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        # type: (...) -> CreateLockDownloadManager

        file_artifacts_by_filename = defaultdict(
            list
        )  # type: DefaultDict[str, List[Tuple[FileArtifact, ProjectName, Version]]]
        source_artifacts_by_pin = (
            {}
        )  # type: Dict[Pin, Tuple[Union[LocalProjectArtifact, VCSArtifact], ProjectName]]
        for locked_resolve in locked_resolves:
            for locked_requirement in locked_resolve.locked_requirements:
                pin = locked_requirement.pin
                project_name = pin.project_name
                for artifact in locked_requirement.iter_artifacts():
                    if isinstance(artifact, FileArtifact):
                        file_artifacts_by_filename[artifact.filename].append(
                            (artifact, project_name, pin.version)
                        )
                    else:
                        # N.B.: We know there is only ever one local project artifact for a given
                        # locked local project requirement and likewise only one VCS artifact for a
                        # given locked VCS requirement.
                        source_artifacts_by_pin[locked_requirement.pin] = (artifact, project_name)

        path_and_version_by_artifact_and_project_name = (
            {}
        )  # type: Dict[Tuple[AnyArtifact, ProjectName], Tuple[Optional[str], Version]]
        for root, _, files in os.walk(download_dir):
            for f in files:
                artifacts_project_names_and_versions = file_artifacts_by_filename[
                    f
                ]  # type: Sequence[Tuple[AnyArtifact, ProjectName, Version]]
                if not artifacts_project_names_and_versions:
                    project_name_and_version = ProjectNameAndVersion.from_filename(f)
                    pin = Pin.canonicalize(project_name_and_version)
                    artifact, project_name = source_artifacts_by_pin[pin]
                    artifacts_project_names_and_versions = [(artifact, project_name, pin.version)]
                if len(artifacts_project_names_and_versions) > 1:
                    # N.B.: When a universal lock is being created, there can be multiple versions
                    # of the same artifact file when multiple indexes / find-links repos are being
                    # used; e.g.: we can get a wheel like
                    # triton-3.4.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl both
                    # from PyPI and https://download.pytorch.org and the wheels will have different
                    # contents. Although this very difference is really not OK, it is the current
                    # state of affairs at least until / if WheelNext (https://wheelnext.dev/) rolls
                    # out solutions. Since `pip download` will have deposited all files in a single
                    # download directory, the last downloaded wheel of a given name will win, and we
                    # won't have proper access to the correct bytes to hash for each wheel. As such
                    # we "forget" the downloaded wheel paths here re-download them later in
                    # `store_all` to individual download directories.
                    #
                    # See: https://github.com/pex-tool/pex/issues/2631
                    for artifact_project_name_and_version in artifacts_project_names_and_versions:
                        artifact, project_name, version = artifact_project_name_and_version
                        path_and_version_by_artifact_and_project_name[(artifact, project_name)] = (
                            None,
                            version,
                        )
                else:
                    artifact, project_name, version = artifacts_project_names_and_versions[0]
                    path_and_version_by_artifact_and_project_name[(artifact, project_name)] = (
                        os.path.join(root, f),
                        version,
                    )

        return cls(
            path_and_version_by_artifact_and_project_name=path_and_version_by_artifact_and_project_name,
            pex_root=pex_root,
        )

    def __init__(
        self,
        path_and_version_by_artifact_and_project_name,  # type: Mapping[Tuple[AnyArtifact, ProjectName], Tuple[Optional[str], Optional[Version]]]
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        # type: (...) -> None
        super(CreateLockDownloadManager, self).__init__(pex_root=pex_root)
        self._path_and_version_by_artifact_and_project_name = dict(
            path_and_version_by_artifact_and_project_name
        )

    def store_all(
        self,
        targets,  # type: Iterable[Target]
        lock_configuration,  # type: LockConfiguration
        resolver,  # type: Resolver
        repos_configuration=ReposConfiguration(),  # type: ReposConfiguration
        max_parallel_jobs=None,  # type: Optional[int]
        pip_version=None,  # type: Optional[PipVersionValue]
        resolver_version=None,  # type: Optional[ResolverVersion.Value]
        network_configuration=None,  # type: Optional[NetworkConfiguration]
        build_configuration=BuildConfiguration(),  # type: BuildConfiguration
        use_pip_config=False,  # type: bool
        extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
        keyring_provider=None,  # type: Optional[str]
    ):
        # type: (...) -> None

        downloadable_artifacts = [
            DownloadableArtifact(project_name=project_name, artifact=artifact, version=version)
            for (artifact, project_name), (
                path,
                version,
            ) in self._path_and_version_by_artifact_and_project_name.items()
            if path is None
        ]
        downloader = LockDownloader.create(
            targets=targets,
            lock_configuration=lock_configuration,
            resolver=resolver,
            repos_configuration=repos_configuration,
            max_parallel_jobs=max_parallel_jobs,
            pip_version=pip_version,
            resolver_version=resolver_version,
            network_configuration=network_configuration,
            build_configuration=build_configuration,
            use_pip_config=use_pip_config,
            extra_pip_requirements=extra_pip_requirements,
            keyring_provider=keyring_provider,
        )
        downloaded_artifacts = try_(
            downloader.download_artifacts(
                tuple(
                    (downloadable_artifact, target)
                    for downloadable_artifact in downloadable_artifacts
                    for target in targets
                )
            )
        )
        for downloadable_artifact, downloaded_artifact in downloaded_artifacts.items():
            # N.B.: The input to download_artifacts above were entries from
            # self._path_and_version_by_artifact_and_project_name which only contains AnyArtifacts.
            artifact = cast("AnyArtifact", downloadable_artifact.artifact)
            production_assert(
                isinstance(artifact, (FileArtifact, LocalProjectArtifact, VCSArtifact))
            )

            self._path_and_version_by_artifact_and_project_name[
                (artifact, downloadable_artifact.project_name)
            ] = (downloaded_artifact.path, downloadable_artifact.version)

        for artifact, project_name in self._path_and_version_by_artifact_and_project_name:
            self.store(artifact, project_name)

    def save(
        self,
        artifact,  # type: Artifact
        project_name,  # type: ProjectName
        dest_dir,  # type: str
        digest,  # type: HintedDigest
    ):
        # type: (...) -> Union[str, Error]

        # N.B.: The input to save comes from self.store in self.store_all above and these inputs
        # are all AnyArtifacts.
        artifact_to_store = cast("AnyArtifact", artifact)
        production_assert(
            isinstance(artifact_to_store, (FileArtifact, LocalProjectArtifact, VCSArtifact))
        )

        path, _ = self._path_and_version_by_artifact_and_project_name[
            (artifact_to_store, project_name)
        ]
        # N.B.: We filled out all None paths above in store_all or else failed if downloads failed
        # there.
        src = cast(str, path)
        production_assert(isinstance(src, str))

        filename = os.path.basename(src)
        dest = os.path.join(dest_dir, filename)
        shutil.move(src, dest)

        hashing.file_hash(dest, digest=digest)
        return filename


@attr.s(frozen=True)
class _LockAnalysis(object):
    download_target = attr.ib()  # type: DownloadTarget
    analyzer = attr.ib()  # type: Locker
    download_dir = attr.ib()  # type: str


class LockError(Exception):
    """Indicates an error creating a lock file."""


def _prepare_project_directory(build_request):
    # type: (BuildRequest) -> Tuple[Target, str]
    return build_request.target, build_request.prepare()


@attr.s(frozen=True)
class LockObserver(ResolveObserver):
    root_requirements = attr.ib()  # type: Tuple[ParsedRequirement, ...]
    lock_style = attr.ib()  # type: LockStyle.Value
    resolver = attr.ib()  # type: Resolver
    wheel_builder = attr.ib()  # type: WheelBuilder
    package_index_configuration = attr.ib()  # type: PackageIndexConfiguration
    max_parallel_jobs = attr.ib(default=None)  # type: Optional[int]
    _analysis = attr.ib(factory=OrderedSet, eq=False)  # type: OrderedSet[_LockAnalysis]

    def observe_download(
        self,
        download_target,  # type: DownloadTarget
        download_dir,  # type: str
    ):
        # type: (...) -> DownloadObserver
        analyzer = Locker(
            target=download_target.target,
            root_requirements=self.root_requirements,
            pip_version=self.package_index_configuration.pip_version,
            resolver=self.resolver,
            lock_style=self.lock_style,
            download_dir=download_dir,
            fingerprint_service=FingerprintService.create(
                url_fetcher=URLFetcher(
                    network_configuration=self.package_index_configuration.network_configuration,
                    password_entries=self.package_index_configuration.password_entries,
                ),
                max_parallel_jobs=self.max_parallel_jobs,
            ),
        )
        patch_set = locker.patch(universal_target=download_target.universal_target)
        observer = DownloadObserver(analyzer=analyzer, patch_set=patch_set)
        self._analysis.add(
            _LockAnalysis(
                download_target=download_target, analyzer=analyzer, download_dir=download_dir
            )
        )
        return observer

    def _spawn_prepare_metadata(self, target_and_project_directory):
        # type: (Tuple[Target, str]) -> SpawnedJob[DistMetadata]

        target, project_directory = target_and_project_directory
        return pep_517.spawn_prepare_metadata(
            project_directory=project_directory,
            pip_version=self.package_index_configuration.pip_version,
            target=target,
            resolver=self.resolver,
        )

    def lock(self, downloaded):
        # type: (Downloaded) -> Tuple[LockedResolve, ...]

        dist_metadatas_by_download_target = defaultdict(
            OrderedSet
        )  # type: DefaultDict[DownloadTarget, OrderedSet[DistMetadata]]
        build_requests = OrderedSet()  # type: OrderedSet[BuildRequest]

        for local_distribution in downloaded.local_distributions:
            if local_distribution.is_wheel:
                dist_metadatas_by_download_target[local_distribution.download_target].add(
                    DistMetadata.load(local_distribution.path)
                )
            else:
                build_requests.add(
                    BuildRequest.create(
                        target=local_distribution.download_target,
                        source_path=local_distribution.path,
                        subdirectory=local_distribution.subdirectory,
                    )
                )

        resolved_requirements_by_download_target = (
            OrderedDict()
        )  # type: OrderedDict[DownloadTarget, Tuple[ResolvedRequirement, ...]]
        for analysis in self._analysis:
            lock_result = analysis.analyzer.lock_result
            build_requests.update(
                BuildRequest.create(target=analysis.download_target, source_path=local_project)
                for local_project in lock_result.local_projects
            )
            resolved_requirements_by_download_target[
                analysis.download_target
            ] = lock_result.resolved_requirements

        with TRACER.timed(
            "Building {count} source {distributions} to gather metadata for lock.".format(
                count=len(build_requests), distributions=pluralize(build_requests, "distribution")
            )
        ):
            pool = ThreadPool(processes=self.max_parallel_jobs)
            try:
                targets_and_project_directories = list(
                    pool.map(_prepare_project_directory, build_requests),
                )
            finally:
                pool.close()
                pool.join()

            build_wheel_requests = []  # type: List[BuildRequest]
            prepare_metadata_errors = OrderedDict()  # type: OrderedDict[str, str]
            for build_request, dist_metadata_result in zip(
                build_requests,
                # MyPy can't infer the _I type argument of Tuple[Target, str] here.
                execute_parallel(  # type: ignore[misc]
                    targets_and_project_directories,
                    # MyPy just can't figure out the next two args types; they're OK.
                    self._spawn_prepare_metadata,  # type: ignore[arg-type]
                    error_handler=Retain[str](),  # type: ignore[arg-type]
                    max_jobs=self.max_parallel_jobs,
                ),
            ):
                if isinstance(dist_metadata_result, DistMetadata):
                    dist_metadatas_by_download_target[build_request.download_target].add(
                        dist_metadata_result
                    )
                else:
                    _item, error = dist_metadata_result
                    if isinstance(error, Job.Error) and pep_517.is_hook_unavailable_error(error):
                        TRACER.log(
                            "Failed to prepare metadata for {project}, trying to build a wheel "
                            "instead: {err}".format(
                                project=build_request.source_path, err=dist_metadata_result
                            ),
                            V=3,
                        )
                        build_wheel_requests.append(build_request)
                    else:
                        prepare_metadata_errors[build_request.source_path] = str(error)

            if prepare_metadata_errors:
                raise LockError(
                    "Could not gather lock metadata for {count} {projects} with source artifacts:\n"
                    "{errors}".format(
                        count=len(prepare_metadata_errors),
                        projects=pluralize(prepare_metadata_errors, "project"),
                        errors="\n".join(
                            "{index}. {project}: {error}".format(
                                index=index, project=project, error=error
                            )
                            for index, (project, error) in enumerate(
                                prepare_metadata_errors.items(), start=1
                            )
                        ),
                    )
                )

            if build_wheel_requests:
                build_wheel_results = self.wheel_builder.build_wheels(
                    build_requests=build_wheel_requests,
                    max_parallel_jobs=self.max_parallel_jobs,
                    # We don't need a compatible wheel, we'll accept metadata from any wheel since
                    # we assume metadata consistency across wheels in general.
                    check_compatible=False,
                )
                for install_requests in build_wheel_results.values():
                    for install_request in install_requests:
                        dist_metadatas_by_download_target[install_request.download_target].add(
                            DistMetadata.load(install_request.wheel_path)
                        )

        universal_targets = tuple(
            download_target.universal_target
            for download_target in resolved_requirements_by_download_target
            if download_target.universal_target
        )
        return tuple(
            LockedResolve.create(
                resolved_requirements=resolved_requirements,
                dist_metadatas=dist_metadatas_by_download_target[download_target],
                fingerprinter=ArtifactDownloader(
                    resolver=self.resolver,
                    universal_target=download_target.universal_target,
                    target=download_target.target,
                    package_index_configuration=self.package_index_configuration,
                    max_parallel_jobs=self.max_parallel_jobs,
                ),
                platform_tag=(
                    None
                    if self.lock_style == LockStyle.UNIVERSAL
                    else download_target.target.platform.tag
                ),
                marker=(
                    download_target.universal_target.marker()
                    if download_target.universal_target and len(universal_targets) > 1
                    else None
                ),
            )
            for download_target, resolved_requirements in resolved_requirements_by_download_target.items()
        )


def create(
    lock_configuration,  # type: LockConfiguration
    requirement_configuration,  # type: RequirementConfiguration
    targets,  # type: Targets
    pip_configuration,  # type: PipConfiguration
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> Union[Lockfile, Error]
    """Create a lock file for the given resolve configurations."""

    network_configuration = pip_configuration.network_configuration
    parsed_requirements = tuple(requirement_configuration.parse_requirements(network_configuration))
    constraints = tuple(
        parsed_constraint.requirement.as_constraint()
        for parsed_constraint in requirement_configuration.parse_constraints(network_configuration)
    )

    password_database = PasswordDatabase.from_netrc().append(
        pip_configuration.repos_configuration.password_entries
    )
    package_index_configuration = PackageIndexConfiguration.create(
        pip_version=pip_configuration.version,
        resolver_version=pip_configuration.resolver_version,
        network_configuration=network_configuration,
        repos_configuration=attr.evolve(
            pip_configuration.repos_configuration, password_entries=password_database.entries
        ),
        use_pip_config=pip_configuration.use_pip_config,
        extra_pip_requirements=pip_configuration.extra_requirements,
        keyring_provider=pip_configuration.keyring_provider,
    )

    configured_resolver = ConfiguredResolver(pip_configuration=pip_configuration)
    lock_observer = LockObserver(
        root_requirements=parsed_requirements,
        lock_style=lock_configuration.style,
        resolver=configured_resolver,
        wheel_builder=WheelBuilder(
            package_index_configuration=package_index_configuration,
            build_configuration=pip_configuration.build_configuration,
            pip_version=pip_configuration.version,
            resolver=configured_resolver,
        ),
        package_index_configuration=package_index_configuration,
        max_parallel_jobs=pip_configuration.max_jobs,
    )

    download_dir = safe_mkdtemp()
    with TRACER.timed("Calculating lock targets"):
        lock_targets = LockTargets.calculate(
            targets=targets,
            requirement_configuration=requirement_configuration,
            network_configuration=network_configuration,
            repos_configuration=pip_configuration.repos_configuration,
            universal_target=lock_configuration.universal_target,
        )
    try:
        downloaded = pip_download(
            targets=lock_targets.targets,
            requirements=requirement_configuration.requirements,
            requirement_files=requirement_configuration.requirement_files,
            constraint_files=requirement_configuration.constraint_files,
            allow_prereleases=pip_configuration.allow_prereleases,
            transitive=pip_configuration.transitive,
            repos_configuration=pip_configuration.repos_configuration,
            resolver_version=pip_configuration.resolver_version,
            network_configuration=network_configuration,
            build_configuration=pip_configuration.build_configuration,
            max_parallel_jobs=pip_configuration.max_jobs,
            observer=lock_observer,
            dest=download_dir,
            pip_log=pip_configuration.log,
            pip_version=pip_configuration.version,
            resolver=configured_resolver,
            use_pip_config=pip_configuration.use_pip_config,
            extra_pip_requirements=pip_configuration.extra_requirements,
            keyring_provider=pip_configuration.keyring_provider,
            dependency_configuration=dependency_configuration,
            universal_targets=lock_targets.universal_targets,
        )
    except resolvers.ResolveError as e:
        return Error(str(e))

    with TRACER.timed("Creating lock from resolve"):
        locked_resolves = lock_observer.lock(downloaded)

    with TRACER.timed("Indexing downloads"):
        create_lock_download_manager = CreateLockDownloadManager.create(
            download_dir=download_dir, locked_resolves=locked_resolves
        )
        create_lock_download_manager.store_all(
            targets=lock_targets.targets.unique_targets(),
            lock_configuration=lock_configuration,
            resolver=configured_resolver,
            repos_configuration=pip_configuration.repos_configuration,
            max_parallel_jobs=pip_configuration.max_jobs,
            pip_version=pip_configuration.version,
            resolver_version=pip_configuration.resolver_version,
            network_configuration=network_configuration,
            build_configuration=pip_configuration.build_configuration,
            use_pip_config=pip_configuration.use_pip_config,
            extra_pip_requirements=pip_configuration.extra_requirements,
            keyring_provider=pip_configuration.keyring_provider,
        )

    lock = Lockfile.create(
        pex_version=__version__,
        lock_configuration=lock_configuration,
        pip_version=pip_configuration.version,
        resolver_version=pip_configuration.resolver_version,
        requirements=parsed_requirements,
        constraints=constraints,
        allow_prereleases=pip_configuration.allow_prereleases,
        build_configuration=pip_configuration.build_configuration,
        transitive=pip_configuration.transitive,
        excluded=dependency_configuration.excluded,
        overridden=dependency_configuration.all_overrides(),
        locked_resolves=locked_resolves,
    )

    if lock_configuration.style is LockStyle.UNIVERSAL and (
        targets.platforms or targets.complete_platforms
    ):
        check_targets = Targets(
            platforms=targets.platforms, complete_platforms=targets.complete_platforms
        )
        with TRACER.timed(
            "Checking lock can resolve for platforms: {targets}".format(targets=check_targets)
        ):
            try_(
                lock_resolver.resolve_from_pex_lock(
                    targets=check_targets,
                    lock=lock,
                    resolver=configured_resolver,
                    repos_configuration=pip_configuration.repos_configuration,
                    resolver_version=pip_configuration.resolver_version,
                    network_configuration=network_configuration,
                    build_configuration=pip_configuration.build_configuration,
                    transitive=pip_configuration.transitive,
                    max_parallel_jobs=pip_configuration.max_jobs,
                    pip_version=pip_configuration.version,
                    use_pip_config=pip_configuration.use_pip_config,
                    extra_pip_requirements=pip_configuration.extra_requirements,
                    dependency_configuration=dependency_configuration,
                )
            )

    return lock
