# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import shutil
import tarfile
from collections import OrderedDict, defaultdict
from multiprocessing.pool import ThreadPool

from pex import hashing, resolver
from pex.auth import PasswordDatabase
from pex.build_system import pep_517
from pex.common import open_zip, pluralize, safe_mkdtemp
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import DistMetadata, ProjectNameAndVersion, is_tar_sdist, is_zip_sdist
from pex.fetcher import URLFetcher
from pex.jobs import Job, Retain, SpawnedJob, execute_parallel
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.pip.download_observer import DownloadObserver
from pex.pip.tool import PackageIndexConfiguration
from pex.resolve import lock_resolver, locker, resolvers
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.downloads import ArtifactDownloader
from pex.resolve.locked_resolve import (
    Artifact,
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
from pex.resolve.pep_691.fingerprint_service import FingerprintService
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolved_requirement import Pin, ResolvedRequirement
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolve.resolvers import Resolver
from pex.resolver import BuildRequest, Downloaded, ResolveObserver, WheelBuilder
from pex.result import Error, try_
from pex.targets import Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.variables import ENV, Variables
from pex.version import __version__

if TYPE_CHECKING:
    from typing import DefaultDict, Dict, Iterable, List, Mapping, Optional, Tuple, Union

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

        file_artifacts_by_filename = {}  # type: Dict[str, Tuple[FileArtifact, ProjectName]]
        source_artifacts_by_pin = (
            {}
        )  # type: Dict[Pin, Tuple[Union[LocalProjectArtifact, VCSArtifact], ProjectName]]
        for locked_resolve in locked_resolves:
            for locked_requirement in locked_resolve.locked_requirements:
                pin = locked_requirement.pin
                project_name = pin.project_name
                for artifact in locked_requirement.iter_artifacts():
                    if isinstance(artifact, FileArtifact):
                        file_artifacts_by_filename[artifact.filename] = (artifact, project_name)
                    else:
                        # N.B.: We know there is only ever one local project artifact for a given
                        # locked local project requirement and likewise only one VCS artifact for a
                        # given locked VCS requirement.
                        source_artifacts_by_pin[locked_requirement.pin] = (artifact, project_name)

        path_by_artifact_and_project_name = {}  # type: Dict[Tuple[Artifact, ProjectName], str]
        for root, _, files in os.walk(download_dir):
            for f in files:
                artifact_and_project_name = file_artifacts_by_filename.get(
                    f
                )  # type: Optional[Tuple[AnyArtifact, ProjectName]]
                if not artifact_and_project_name:
                    project_name_and_version = ProjectNameAndVersion.from_filename(f)
                    pin = Pin.canonicalize(project_name_and_version)
                    artifact_and_project_name = source_artifacts_by_pin[pin]
                path_by_artifact_and_project_name[artifact_and_project_name] = os.path.join(root, f)

        return cls(
            path_by_artifact_and_project_name=path_by_artifact_and_project_name, pex_root=pex_root
        )

    def __init__(
        self,
        path_by_artifact_and_project_name,  # type: Mapping[Tuple[Artifact, ProjectName], str]
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        # type: (...) -> None
        super(CreateLockDownloadManager, self).__init__(pex_root=pex_root)
        self._path_by_artifact_and_project_name = path_by_artifact_and_project_name

    def store_all(self):
        # type: () -> None
        for artifact, project_name in self._path_by_artifact_and_project_name:
            self.store(artifact, project_name)

    def save(
        self,
        artifact,  # type: Artifact
        project_name,  # type: ProjectName
        dest_dir,  # type: str
        digest,  # type: HintedDigest
    ):
        # type: (...) -> Union[str, Error]
        src = self._path_by_artifact_and_project_name[(artifact, project_name)]
        filename = os.path.basename(src)
        dest = os.path.join(dest_dir, filename)
        shutil.move(src, dest)

        hashing.file_hash(dest, digest=digest)
        return filename


@attr.s(frozen=True)
class _LockAnalysis(object):
    target = attr.ib()  # type: Target
    analyzer = attr.ib()  # type: Locker
    download_dir = attr.ib()  # type: str


class LockError(Exception):
    """Indicates an error creating a lock file."""


def _prepare_project_directory(build_request):
    # type: (BuildRequest) -> Tuple[Target, str]

    project = build_request.source_path
    target = build_request.target
    if os.path.isdir(project):
        return target, project

    extract_dir = os.path.join(safe_mkdtemp(), "project")
    if is_zip_sdist(project):
        with open_zip(project) as zf:
            zf.extractall(extract_dir)
    elif is_tar_sdist(project):
        with tarfile.open(project) as tf:
            tf.extractall(extract_dir)
    else:
        raise LockError("Unexpected archive type for sdist {project}".format(project=project))

    listing = os.listdir(extract_dir)
    if len(listing) != 1:
        raise LockError(
            "Expected one top-level project directory to be extracted from {project}, "
            "found {count}: {listing}".format(
                project=project, count=len(listing), listing=", ".join(listing)
            )
        )
    return target, os.path.join(extract_dir, listing[0])


@attr.s(frozen=True)
class LockObserver(ResolveObserver):
    root_requirements = attr.ib()  # type: Tuple[ParsedRequirement, ...]
    lock_configuration = attr.ib()  # type: LockConfiguration
    resolver = attr.ib()  # type: Resolver
    wheel_builder = attr.ib()  # type: WheelBuilder
    package_index_configuration = attr.ib()  # type: PackageIndexConfiguration
    max_parallel_jobs = attr.ib(default=None)  # type: Optional[int]
    _analysis = attr.ib(factory=OrderedSet, eq=False)  # type: OrderedSet[_LockAnalysis]

    def observe_download(
        self,
        target,  # type: Target
        download_dir,  # type: str
    ):
        # type: (...) -> DownloadObserver
        analyzer = Locker(
            target=target,
            root_requirements=self.root_requirements,
            pip_version=self.package_index_configuration.pip_version,
            resolver=self.resolver,
            lock_configuration=self.lock_configuration,
            download_dir=download_dir,
            fingerprint_service=FingerprintService.create(
                url_fetcher=URLFetcher(
                    network_configuration=self.package_index_configuration.network_configuration,
                    password_entries=self.package_index_configuration.password_entries,
                ),
                max_parallel_jobs=self.max_parallel_jobs,
            ),
        )
        patch_set = locker.patch(lock_configuration=self.lock_configuration)
        observer = DownloadObserver(analyzer=analyzer, patch_set=patch_set)
        self._analysis.add(
            _LockAnalysis(target=target, analyzer=analyzer, download_dir=download_dir)
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

        dist_metadatas_by_target = defaultdict(
            OrderedSet
        )  # type: DefaultDict[Target, OrderedSet[DistMetadata]]
        build_requests = OrderedSet()  # type: OrderedSet[BuildRequest]

        for local_distribution in downloaded.local_distributions:
            if local_distribution.is_wheel:
                dist_metadatas_by_target[local_distribution.target].add(
                    DistMetadata.load(local_distribution.path)
                )
            else:
                build_requests.add(
                    BuildRequest.create(
                        target=local_distribution.target, source_path=local_distribution.path
                    )
                )

        resolved_requirements_by_target = (
            OrderedDict()
        )  # type: OrderedDict[Target, Tuple[ResolvedRequirement, ...]]
        for analysis in self._analysis:
            lock_result = analysis.analyzer.lock_result
            build_requests.update(
                BuildRequest.create(target=analysis.target, source_path=local_project)
                for local_project in lock_result.local_projects
            )
            resolved_requirements_by_target[analysis.target] = lock_result.resolved_requirements

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
                    dist_metadatas_by_target[build_request.target].add(dist_metadata_result)
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
                        dist_metadatas_by_target[install_request.target].add(
                            DistMetadata.load(install_request.wheel_path)
                        )

        return tuple(
            LockedResolve.create(
                resolved_requirements=resolved_requirements,
                dist_metadatas=dist_metadatas_by_target[target],
                fingerprinter=ArtifactDownloader(
                    resolver=self.resolver,
                    lock_configuration=self.lock_configuration,
                    target=target,
                    package_index_configuration=self.package_index_configuration,
                    max_parallel_jobs=self.max_parallel_jobs,
                ),
                platform_tag=(
                    None
                    if self.lock_configuration.style == LockStyle.UNIVERSAL
                    else target.platform.tag
                ),
            )
            for target, resolved_requirements in resolved_requirements_by_target.items()
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

    package_index_configuration = PackageIndexConfiguration.create(
        pip_version=pip_configuration.version,
        resolver_version=pip_configuration.resolver_version,
        network_configuration=network_configuration,
        find_links=pip_configuration.repos_configuration.find_links,
        indexes=pip_configuration.repos_configuration.indexes,
        password_entries=(
            PasswordDatabase.from_netrc()
            .append(pip_configuration.repos_configuration.password_entries)
            .entries
        ),
        use_pip_config=pip_configuration.use_pip_config,
        extra_pip_requirements=pip_configuration.extra_requirements,
        keyring_provider=pip_configuration.keyring_provider,
    )

    configured_resolver = ConfiguredResolver(pip_configuration=pip_configuration)
    lock_observer = LockObserver(
        root_requirements=parsed_requirements,
        lock_configuration=lock_configuration,
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

    if lock_configuration.style is LockStyle.UNIVERSAL:
        download_targets = (
            Targets(interpreters=(targets.interpreter,)) if targets.interpreter else Targets()
        )
    else:
        download_targets = targets

    try:
        downloaded = resolver.download(
            targets=download_targets,
            requirements=requirement_configuration.requirements,
            requirement_files=requirement_configuration.requirement_files,
            constraint_files=requirement_configuration.constraint_files,
            allow_prereleases=pip_configuration.allow_prereleases,
            transitive=pip_configuration.transitive,
            indexes=pip_configuration.repos_configuration.indexes,
            find_links=pip_configuration.repos_configuration.find_links,
            resolver_version=pip_configuration.resolver_version,
            network_configuration=network_configuration,
            password_entries=pip_configuration.repos_configuration.password_entries,
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
        )
    except resolvers.ResolveError as e:
        return Error(str(e))

    with TRACER.timed("Creating lock from resolve"):
        locked_resolves = lock_observer.lock(downloaded)

    with TRACER.timed("Indexing downloads"):
        create_lock_download_manager = CreateLockDownloadManager.create(
            download_dir=download_dir, locked_resolves=locked_resolves
        )
        create_lock_download_manager.store_all()

    lock = Lockfile.create(
        pex_version=__version__,
        style=lock_configuration.style,
        requires_python=lock_configuration.requires_python,
        target_systems=lock_configuration.target_systems,
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
        elide_unused_requires_dist=lock_configuration.elide_unused_requires_dist,
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
                lock_resolver.resolve_from_lock(
                    targets=check_targets,
                    lock=lock,
                    resolver=configured_resolver,
                    indexes=pip_configuration.repos_configuration.indexes,
                    find_links=pip_configuration.repos_configuration.find_links,
                    resolver_version=pip_configuration.resolver_version,
                    network_configuration=network_configuration,
                    password_entries=pip_configuration.repos_configuration.password_entries,
                    build_configuration=pip_configuration.build_configuration,
                    transitive=pip_configuration.transitive,
                    max_parallel_jobs=pip_configuration.max_jobs,
                    pip_version=pip_configuration.version,
                    use_pip_config=pip_configuration.use_pip_config,
                    extra_pip_requirements=pip_configuration.extra_requirements,
                )
            )

    return lock
