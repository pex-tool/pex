# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import shutil

from pex import resolver
from pex.common import pluralize, safe_mkdtemp, safe_open
from pex.network_configuration import NetworkConfiguration
from pex.requirements import (
    Constraint,
    LocalProjectRequirement,
    PyPIRequirement,
    URLRequirement,
    VCSRequirement,
    parse_requirement_strings,
)
from pex.resolve import resolvers
from pex.resolve.locked_resolve import Artifact, LockConfiguration
from pex.resolve.lockfile.download_manager import DownloadedArtifact, DownloadManager
from pex.resolve.lockfile.lockfile import Lockfile as Lockfile  # For re-export.
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolver import Downloaded
from pex.result import Error, try_
from pex.targets import Targets
from pex.third_party.pkg_resources import Requirement
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper
from pex.variables import ENV
from pex.version import __version__

if TYPE_CHECKING:
    from typing import Iterable, List, Mapping, Optional, Text, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class ParseError(Exception):
    """Indicates an error parsing a Pex lock file."""


def load(lockfile_path):
    # type: (str) -> Lockfile
    """Loads the Pex lock file stored at the given path.

    :param lockfile_path: The path to the Pex lock file to load.
    :return: The parsed lock file.
    :raises: :class:`ParseError` if there was a problem parsing the lock file.
    """
    from pex.resolve.lockfile import json_codec

    return json_codec.load(lockfile_path=lockfile_path)


def loads(
    lockfile_contents,  # type: Text
    source="<string>",  # type: str
):
    # type: (...) -> Lockfile
    """Parses the given Pex lock file contents.

    :param lockfile_contents: The contents of a Pex lock file.
    :param source: A descriptive name for the source of the lock file contents.
    :return: The parsed lock file.
    :raises: :class:`ParseError` if there was a problem parsing the lock file.
    """
    from pex.resolve.lockfile import json_codec

    return json_codec.loads(lockfile_contents=lockfile_contents, source=source)


def store(
    lockfile,  # type: Lockfile
    path,  # type: str
):
    # type: (...) -> None
    """Stores the given lock file at the given path.

    Any missing parent directories in the path will be created and any pre-existing file at the
    path wil be over-written.

    :param lockfile: The lock file to store.
    :param path: The path to store the lock file at.
    """
    import json

    from pex.resolve.lockfile import json_codec

    with safe_open(path, "w") as fp:
        json.dump(json_codec.as_json_data(lockfile), fp, sort_keys=True)


@attr.s(frozen=True)
class Requirements(object):
    @classmethod
    def create(
        cls,
        parsed_requirements,  # type: Iterable[Union[PyPIRequirement, URLRequirement]]
        parsed_constraints,  # type: Iterable[Constraint]
    ):
        # type: (...) -> Requirements
        return cls(
            parsed_requirements=tuple(parsed_requirements),
            requirements=tuple(
                parsed_requirement.requirement for parsed_requirement in parsed_requirements
            ),
            parsed_constraints=tuple(parsed_constraints),
            constraints=tuple(
                parsed_constraint.requirement for parsed_constraint in parsed_constraints
            ),
        )

    parsed_requirements = attr.ib()  # type: Tuple[Union[PyPIRequirement, URLRequirement], ...]
    requirements = attr.ib()  # type: Tuple[Requirement, ...]
    parsed_constraints = attr.ib()  # type: Tuple[Constraint, ...]
    constraints = attr.ib()  # type: Tuple[Requirement, ...]


def parse_lockable_requirements(
    requirement_configuration,  # type: RequirementConfiguration
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    fallback_requirements=None,  # type: Optional[Iterable[str]]
):
    # type: (...) -> Union[Requirements, Error]

    all_parsed_requirements = requirement_configuration.parse_requirements(network_configuration)
    if not all_parsed_requirements and fallback_requirements:
        all_parsed_requirements = parse_requirement_strings(fallback_requirements)

    parsed_requirements = []  # type: List[Union[PyPIRequirement, URLRequirement]]
    projects = []  # type: List[str]
    for parsed_requirement in all_parsed_requirements:
        if isinstance(parsed_requirement, LocalProjectRequirement):
            projects.append("local project at {path}".format(path=parsed_requirement.path))
        elif isinstance(parsed_requirement, VCSRequirement):
            projects.append(
                "{vcs} project {project_name} at {url}".format(
                    vcs=parsed_requirement.vcs,
                    project_name=parsed_requirement.requirement.project_name,
                    url=parsed_requirement.url,
                )
            )
        else:
            parsed_requirements.append(parsed_requirement)
    if projects:
        return Error(
            "Cannot create a lock for project requirements built from local or version "
            "controlled sources. Given {count} such {projects}:\n{project_descriptions}".format(
                count=len(projects),
                projects=pluralize(projects, "project"),
                project_descriptions="\n".join(
                    "{index}.) {project}".format(index=index, project=project)
                    for index, project in enumerate(projects, start=1)
                ),
            )
        )

    return Requirements.create(
        parsed_requirements=parsed_requirements,
        parsed_constraints=requirement_configuration.parse_constraints(network_configuration),
    )


class CreateLockDownloadManager(DownloadManager):
    @classmethod
    def create(
        cls,
        download_dir,  # type: str
        downloaded,  # type: Downloaded
        pex_root=None,  # type: Optional[str]
    ):
        # type: (...) -> CreateLockDownloadManager

        artifacts_by_filename = {
            artifact.filename: artifact
            for locked_resolve in downloaded.locked_resolves
            for locked_requirement in locked_resolve.locked_requirements
            for artifact in locked_requirement.iter_artifacts()
        }
        path_by_artifact = {
            artifacts_by_filename[f]: os.path.join(root, f)
            for root, _, files in os.walk(download_dir)
            for f in files
        }
        return cls(path_by_artifact=path_by_artifact, pex_root=pex_root)

    def __init__(
        self,
        path_by_artifact,  # type: Mapping[Artifact, str]
        pex_root=None,  # type: Optional[str]
    ):
        super(CreateLockDownloadManager, self).__init__(pex_root=pex_root)
        self._path_by_artifact = path_by_artifact

    def store_all(self):
        for artifact in self._path_by_artifact:
            self.store(artifact)

    def save(
        self,
        artifact,  # type: Artifact
        path,  # type: str
    ):
        # type: (...) -> str
        shutil.move(self._path_by_artifact[artifact], path)
        return CacheHelper.hash(path)


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
