# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import shutil

from pex import hashing, resolver
from pex.common import safe_mkdtemp
from pex.dist_metadata import ProjectNameAndVersion
from pex.pep_503 import ProjectName
from pex.resolve import resolvers
from pex.resolve.locked_resolve import Artifact, FileArtifact, LockConfiguration, VCSArtifact
from pex.resolve.lockfile.download_manager import DownloadManager
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.lockfile.requirements import parse_lockable_requirements
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolved_requirement import Pin
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolver import Downloaded
from pex.result import Error, try_
from pex.targets import Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from pex.version import __version__

if TYPE_CHECKING:
    from typing import Dict, Mapping, Optional, Tuple, Union

    from pex.hashing import HintedDigest


class CreateLockDownloadManager(DownloadManager[Artifact]):
    @classmethod
    def create(
        cls,
        download_dir,  # type: str
        downloaded,  # type: Downloaded
        pex_root=None,  # type: Optional[str]
    ):
        # type: (...) -> CreateLockDownloadManager

        file_artifacts_by_filename = {}  # type: Dict[str, FileArtifact]
        vcs_artifacts_by_pin = {}  # type: Dict[Pin, VCSArtifact]
        for locked_resolve in downloaded.locked_resolves:
            for locked_requirement in locked_resolve.locked_requirements:
                for artifact in locked_requirement.iter_artifacts():
                    if isinstance(artifact, FileArtifact):
                        file_artifacts_by_filename[artifact.filename] = artifact
                    else:
                        # N.B.: We know there is only ever one VCS artifact for a given locked VCS
                        # requirement.
                        vcs_artifacts_by_pin[locked_requirement.pin] = artifact

        path_by_artifact_and_project_name = {}  # type: Dict[Tuple[Artifact, ProjectName], str]
        for root, _, files in os.walk(download_dir):
            for f in files:
                pin = Pin.canonicalize(ProjectNameAndVersion.from_filename(f))
                artifact = file_artifacts_by_filename.get(f) or vcs_artifacts_by_pin[pin]
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


def create(
    lock_configuration,  # type: LockConfiguration
    requirement_configuration,  # type: RequirementConfiguration
    targets,  # type: Targets
    pip_configuration,  # type: PipConfiguration
):
    # type: (...) -> Union[Lockfile, Error]
    """Create a lock file for the given resolve configurations."""

    network_configuration = pip_configuration.network_configuration
    parsed_requirements = try_(
        parse_lockable_requirements(
            requirement_configuration, network_configuration=network_configuration
        )
    )

    dest = safe_mkdtemp()

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
            cache=ENV.PEX_ROOT,
            build=pip_configuration.allow_builds,
            use_wheel=pip_configuration.allow_wheels,
            prefer_older_binary=pip_configuration.prefer_older_binary,
            use_pep517=pip_configuration.use_pep517,
            build_isolation=pip_configuration.build_isolation,
            max_parallel_jobs=pip_configuration.max_jobs,
            lock_configuration=lock_configuration,
            dest=dest,
        )
    except resolvers.ResolveError as e:
        return Error(str(e))

    with TRACER.timed("Indexing downloads"):
        create_lock_download_manager = CreateLockDownloadManager.create(
            download_dir=dest, downloaded=downloaded
        )
        create_lock_download_manager.store_all()

    return Lockfile.create(
        pex_version=__version__,
        style=lock_configuration.style,
        requires_python=lock_configuration.requires_python,
        resolver_version=pip_configuration.resolver_version,
        requirements=parsed_requirements.requirements,
        constraints=parsed_requirements.constraints,
        allow_prereleases=pip_configuration.allow_prereleases,
        allow_wheels=pip_configuration.allow_wheels,
        allow_builds=pip_configuration.allow_builds,
        prefer_older_binary=pip_configuration.prefer_older_binary,
        use_pep517=pip_configuration.use_pep517,
        build_isolation=pip_configuration.build_isolation,
        transitive=pip_configuration.transitive,
        locked_resolves=downloaded.locked_resolves,
    )
