# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import functools
import hashlib
from multiprocessing.pool import ThreadPool

from pex.commands.command import Error, try_
from pex.compatibility import cpu_count
from pex.fetcher import URLFetcher
from pex.network_configuration import NetworkConfiguration
from pex.resolve import lockfile
from pex.resolve.locked_resolve import DownloadableArtifact
from pex.resolve.lockfile import parse_lockable_requirements
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolvers import Installed, InstalledDistribution
from pex.targets import Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, Iterable, List, Optional, Union


def resolve_from_lock(
    targets,  # type: Targets
    lockfile_path,  # type: str
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    constraint_files=None,  # type: Optional[Iterable[str]]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    transitive=True,  # type: bool
    ignore_errors=False,  # type: bool
    max_jobs=None,  # type: Optional[int]
):
    # type: (...) -> Union[Installed, Error]

    lock = lockfile.load(lockfile_path)

    requirement_configuration = RequirementConfiguration(
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
    )
    parsed_requirements = try_(
        parse_lockable_requirements(
            requirement_configuration, network_configuration=network_configuration
        )
    )

    downloadable_artifacts = []  # type: List[DownloadableArtifact]
    downloadable_artifacts_by_target = {}  # type: Dict[Target, Iterable[DownloadableArtifact]]

    with TRACER.timed(
        "Resolving urls to fetch for {count} requirements from lock {lockfile}.".format(
            count=len(parsed_requirements.requirements), lockfile=lockfile_path
        )
    ):
        for target, locked_resolve in lock.select(targets.unique_targets()):
            # TODO(John Sirois): Gather up all results and return a comprehensive Error if multiple
            #  targets fail to resolve instead of erring eagerly.
            resolved = try_(
                locked_resolve.resolve(
                    target, parsed_requirements.requirements, transitive=transitive
                )
            )
            downloadable_artifacts_by_target[target] = resolved.downloadable_artifacts
            downloadable_artifacts.extend(resolved.downloadable_artifacts)

    url_fetcher = URLFetcher(network_configuration=network_configuration, handle_file_urls=True)

    # TODO(John Sirois): XXX: We want to download once and only once so each URL needs a lock
    #  (atomic_directory) and after gaining the lock we only want to download those urls - the rest
    #  are done.

    max_threads = min(len(downloadable_artifacts), 4 * (max_jobs or cpu_count() or 1))

    with TRACER.timed(
        "Downloading {url_count} distributions to satisfy {requirement_count} requirements.".format(
            url_count=len(downloadable_artifacts),
            requirement_count=len(parsed_requirements.requirements),
        )
    ):
        pool = ThreadPool(processes=max_threads)
        try:
            # TODO(John Sirois): XXX: Gather up the str | Error that come back from each of these.
            pool.map(functools.partial(_download, url_fetcher), downloadable_artifacts)
        finally:
            pool.close()
            pool.join()

    if not ignore_errors:
        _constraints = parsed_requirements.constraints
        # TODO(John Sirois): XXX validate the resolve meets constraints.

    installed_distributions = []  # type: List[InstalledDistribution]
    # TODO(John Sirois): XXX: BuildAndInstall downloaded distributions.
    return Installed(installed_distributions=tuple(installed_distributions))


_BUFFER_SIZE = 65536


def _download(
    url_fetcher,  # type: URLFetcher
    downloadable_artifact,  # type: DownloadableArtifact
):
    # type: (...) -> Union[str, Error]
    artifact = downloadable_artifact.artifact
    digest = hashlib.new(artifact.fingerprint.algorithm)
    with open("", "wb") as fp, url_fetcher.get_body_stream(artifact.url) as stream:
        for chunk in iter(lambda: stream.read(_BUFFER_SIZE), b""):
            fp.write(chunk)
            digest.update(chunk)
    actual_hash = digest.hexdigest()
    if artifact.fingerprint.hash != actual_hash:
        # TODO(John Sirois): XXX: Use pin and direct_requirements information to flesh out message.
        return Error(
            "Artifact downloaded from {url} was expected to have {algorithm} hash of "
            "{expected_hash} but it hashed to {actual_hash}.".format(
                url=artifact.url,
                algorithm=artifact.fingerprint.algorithm,
                expected_hash=artifact.fingerprint.hash,
                actual_hash=actual_hash,
            )
        )
    return fp.name
