# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import shutil
from collections import OrderedDict, defaultdict

from pex import hashing, resolver
from pex.auth import PasswordDatabase
from pex.common import pluralize, safe_mkdtemp
from pex.dist_metadata import DistMetadata, ProjectNameAndVersion
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.pip.download_observer import DownloadObserver
from pex.pip.tool import PackageIndexConfiguration
from pex.resolve import locker, resolvers
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
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolved_requirement import Pin, ResolvedRequirement
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolve.resolvers import Resolver
from pex.resolver import BuildRequest, Downloaded, ResolveObserver, WheelBuilder
from pex.result import Error
from pex.targets import Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.version import __version__

if TYPE_CHECKING:
    from typing import DefaultDict, Dict, Iterable, Mapping, Optional, Tuple, Union

    import attr  # vendor:skip

    from pex.hashing import HintedDigest
else:
    from pex.third_party import attr


class CreateLockDownloadManager(DownloadManager[Artifact]):
    @classmethod
    def create(
        cls,
        download_dir,  # type: str
        locked_resolves,  # type: Iterable[LockedResolve]
        pex_root=None,  # type: Optional[str]
    ):
        # type: (...) -> CreateLockDownloadManager

        file_artifacts_by_filename = {}  # type: Dict[str, FileArtifact]
        source_artifacts_by_pin = {}  # type: Dict[Pin, Union[LocalProjectArtifact, VCSArtifact]]
        for locked_resolve in locked_resolves:
            for locked_requirement in locked_resolve.locked_requirements:
                for artifact in locked_requirement.iter_artifacts():
                    if isinstance(artifact, FileArtifact):
                        file_artifacts_by_filename[artifact.filename] = artifact
                    else:
                        # N.B.: We know there is only ever one local project artifact for a given
                        # locked local project requirement and likewise only one VCS artifact for a
                        # given locked VCS requirement.
                        source_artifacts_by_pin[locked_requirement.pin] = artifact

        path_by_artifact_and_project_name = {}  # type: Dict[Tuple[Artifact, ProjectName], str]
        for root, _, files in os.walk(download_dir):
            for f in files:
                pin = Pin.canonicalize(ProjectNameAndVersion.from_filename(f))
                artifact = file_artifacts_by_filename.get(f) or source_artifacts_by_pin[pin]
                path_by_artifact_and_project_name[(artifact, pin.project_name)] = os.path.join(
                    root, f
                )

        return cls(
            path_by_artifact_and_project_name=path_by_artifact_and_project_name, pex_root=pex_root
        )

    def __init__(
        self,
        path_by_artifact_and_project_name,  # type: Mapping[Tuple[Artifact, ProjectName], str]
        pex_root=None,  # type: Optional[str]
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


@attr.s(frozen=True)
class LockObserver(ResolveObserver):
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
        patch = locker.patch(
            resolver=self.resolver,
            lock_configuration=self.lock_configuration,
            download_dir=download_dir,
        )
        self._analysis.add(
            _LockAnalysis(target=target, analyzer=patch.analyzer, download_dir=download_dir)
        )
        return patch

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
            build_results = self.wheel_builder.build_wheels(
                build_requests=build_requests,
                max_parallel_jobs=self.max_parallel_jobs,
            )
            for install_requests in build_results.values():
                for install_request in install_requests:
                    dist_metadatas_by_target[install_request.target].add(
                        DistMetadata.load(install_request.wheel_path)
                    )

        return tuple(
            LockedResolve.create(
                resolved_requirements=resolved_requirements,
                dist_metadatas=dist_metadatas_by_target[target],
                fingerprinter=ArtifactDownloader(
                    package_index_configuration=self.package_index_configuration, target=target
                ),
                platform_tag=None
                if self.lock_configuration.style == LockStyle.UNIVERSAL
                else target.platform.tag,
            )
            for target, resolved_requirements in resolved_requirements_by_target.items()
        )


def create(
    lock_configuration,  # type: LockConfiguration
    requirement_configuration,  # type: RequirementConfiguration
    targets,  # type: Targets
    pip_configuration,  # type: PipConfiguration
):
    # type: (...) -> Union[Lockfile, Error]
    """Create a lock file for the given resolve configurations."""

    network_configuration = pip_configuration.network_configuration
    parsed_requirements = tuple(requirement_configuration.parse_requirements(network_configuration))
    constraints = tuple(
        parsed_constraint.requirement
        for parsed_constraint in requirement_configuration.parse_constraints(network_configuration)
    )

    package_index_configuration = PackageIndexConfiguration.create(
        resolver_version=pip_configuration.resolver_version,
        network_configuration=network_configuration,
        find_links=pip_configuration.repos_configuration.find_links,
        indexes=pip_configuration.repos_configuration.indexes,
        password_entries=PasswordDatabase.from_netrc()
        .append(pip_configuration.repos_configuration.password_entries)
        .entries,
    )

    lock_observer = LockObserver(
        lock_configuration=lock_configuration,
        resolver=ConfiguredResolver(pip_configuration=pip_configuration),
        wheel_builder=WheelBuilder(
            package_index_configuration=package_index_configuration,
            prefer_older_binary=pip_configuration.prefer_older_binary,
            use_pep517=pip_configuration.use_pep517,
            build_isolation=pip_configuration.build_isolation,
        ),
        package_index_configuration=package_index_configuration,
        max_parallel_jobs=pip_configuration.max_jobs,
    )

    download_dir = safe_mkdtemp()

    try:
        downloaded = resolver.download(
            targets=targets,
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
            build=pip_configuration.allow_builds,
            use_wheel=pip_configuration.allow_wheels,
            prefer_older_binary=pip_configuration.prefer_older_binary,
            use_pep517=pip_configuration.use_pep517,
            build_isolation=pip_configuration.build_isolation,
            max_parallel_jobs=pip_configuration.max_jobs,
            observer=lock_observer,
            dest=download_dir,
            preserve_log=pip_configuration.preserve_log,
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

    return Lockfile.create(
        pex_version=__version__,
        style=lock_configuration.style,
        requires_python=lock_configuration.requires_python,
        resolver_version=pip_configuration.resolver_version,
        requirements=parsed_requirements,
        constraints=constraints,
        allow_prereleases=pip_configuration.allow_prereleases,
        allow_wheels=pip_configuration.allow_wheels,
        allow_builds=pip_configuration.allow_builds,
        prefer_older_binary=pip_configuration.prefer_older_binary,
        use_pep517=pip_configuration.use_pep517,
        build_isolation=pip_configuration.build_isolation,
        transitive=pip_configuration.transitive,
        locked_resolves=locked_resolves,
    )
