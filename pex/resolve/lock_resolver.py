# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import functools
import hashlib
from collections import OrderedDict
from multiprocessing.pool import ThreadPool

from pex.common import pluralize
from pex.compatibility import cpu_count
from pex.fetcher import URLFetcher
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pip import PackageIndexConfiguration
from pex.resolve import lockfile
from pex.resolve.locked_resolve import Artifact, DownloadableArtifact, Resolved
from pex.resolve.lockfile import parse_lockable_requirements
from pex.resolve.lockfile.download_manager import DownloadedArtifact, DownloadManager
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import ResolverVersion
from pex.resolve.resolvers import Installed
from pex.resolver import BuildAndInstallRequest, BuildRequest, InstallRequest
from pex.result import Error, ResultError, catch, try_
from pex.targets import Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, Iterable, Optional, Sequence, Union


class URLFetcherDownloadManager(DownloadManager):
    _BUFFER_SIZE = 65536

    def __init__(
        self,
        url_fetcher,  # type: URLFetcher
        pex_root=None,  # type: Optional[str]
    ):
        super(URLFetcherDownloadManager, self).__init__(pex_root=pex_root)
        self._url_fetcher = url_fetcher

    def store_downloadable_artifact(self, downloadable_artifact):
        return self.store(artifact=downloadable_artifact.artifact)

    def save(
        self,
        artifact,  # type: Artifact
        path,  # type: str
    ):
        # type: (...) -> str
        digest_check = hashlib.new(artifact.fingerprint.algorithm)
        digest_internal = hashlib.sha1()
        url = artifact.url
        try:
            with open(path, "wb") as fp, self._url_fetcher.get_body_stream(url) as stream:
                for chunk in iter(lambda: stream.read(self._BUFFER_SIZE), b""):
                    fp.write(chunk)
                    digest_check.update(chunk)
                    digest_internal.update(chunk)
        except IOError as e:
            raise ResultError(Error(str(e)))

        actual_hash = digest_check.hexdigest()
        if artifact.fingerprint.hash != actual_hash:
            raise ResultError(
                Error(
                    "Expected {algorithm} hash of {expected_hash} but hashed to "
                    "{actual_hash}.".format(
                        algorithm=artifact.fingerprint.algorithm,
                        expected_hash=artifact.fingerprint.hash,
                        actual_hash=actual_hash,
                    )
                )
            )
        return digest_internal.hexdigest()


# Derived from notes in the bandersnatch PyPI mirroring tool:
# https://github.com/pypa/bandersnatch/blob/1485712d6aa77fba54bbf5a2df0d7314124ad097/src/bandersnatch/default.conf#L30-L35
MAX_PARALLEL_DOWNLOADS = 10


def resolve_from_lock(
    targets,  # type: Targets
    lockfile_path,  # type: str
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    constraint_files=None,  # type: Optional[Iterable[str]]
    indexes=None,  # type: Optional[Sequence[str]]
    find_links=None,  # type: Optional[Sequence[str]]
    resolver_version=None,  # type: Optional[ResolverVersion.Value]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    cache=None,  # type: Optional[str]
    build=True,  # type: bool
    use_wheel=True,  # type: bool
    prefer_older_binary=False,  # type: bool
    use_pep517=None,  # type: Optional[bool]
    build_isolation=True,  # type: bool
    compile=False,  # type: bool
    transitive=True,  # type: bool
    verify_wheels=True,  # type: bool
    max_parallel_jobs=None,  # type: Optional[int]
):
    # type: (...) -> Union[Installed, Error]

    with TRACER.timed("Parsing lock {lockfile}".format(lockfile=lockfile_path)):
        lock = lockfile.load(lockfile_path)

    with TRACER.timed("Parsing requirements"):
        requirement_configuration = RequirementConfiguration(
            requirements=requirements,
            requirement_files=requirement_files,
            constraint_files=constraint_files,
        )
        parsed_requirements = try_(
            parse_lockable_requirements(
                requirement_configuration,
                network_configuration=network_configuration,
                fallback_requirements=(str(req) for req in lock.requirements),
            )
        )

    errors_by_target = {}  # type: Dict[Target, Iterable[Error]]
    downloadable_artifacts = OrderedSet()  # type: OrderedSet[DownloadableArtifact]
    downloadable_artifacts_by_target = {}  # type: Dict[Target, Iterable[DownloadableArtifact]]

    with TRACER.timed(
        "Resolving urls to fetch for {count} requirements from lock {lockfile}".format(
            count=len(parsed_requirements.requirements), lockfile=lockfile_path
        )
    ):
        for target in targets.unique_targets():
            resolveds = []
            errors = []
            for locked_resolve in lock.locked_resolves:
                resolve_result = locked_resolve.resolve(
                    target,
                    parsed_requirements.requirements,
                    constraints=parsed_requirements.constraints,
                    source=lockfile_path,
                    transitive=transitive,
                    build=build,
                    use_wheel=use_wheel,
                    prefer_older_binary=prefer_older_binary,
                    # TODO(John Sirois): Plumb `--ignore-errors` to support desired but technically
                    #  invalid `pip-legacy-resolver` locks:
                    #  https://github.com/pantsbuild/pex/issues/1652
                )
                if isinstance(resolve_result, Resolved):
                    resolveds.append(resolve_result)
                else:
                    errors.append(resolve_result)

            if resolveds:
                resolved = sorted(resolveds, key=lambda res: res.target_specificity)[-1]
                downloadable_artifacts_by_target[target] = resolved.downloadable_artifacts
                downloadable_artifacts.update(resolved.downloadable_artifacts)
            elif errors:
                errors_by_target[target] = tuple(errors)

    if errors_by_target:
        return Error(
            "Failed to resolve compatible artifacts from lock {lock} for {count} {targets}:\n"
            "{errors}".format(
                lock=lock.source,
                count=len(errors_by_target),
                targets=pluralize(errors_by_target, "target"),
                errors="\n".join(
                    "{index}. {target}:\n    {errors}".format(
                        index=index, target=target, errors="\n    ".join(map(str, errors))
                    )
                    for index, (target, errors) in enumerate(errors_by_target.items(), start=1)
                ),
            )
        )

    download_manager = URLFetcherDownloadManager(
        url_fetcher=URLFetcher(network_configuration=network_configuration, handle_file_urls=True)
    )
    max_threads = min(
        len(downloadable_artifacts) or 1,
        min(MAX_PARALLEL_DOWNLOADS, 4 * (max_parallel_jobs or cpu_count() or 1)),
    )
    with TRACER.timed(
        "Downloading {url_count} distributions to satisfy {requirement_count} requirements".format(
            url_count=len(downloadable_artifacts),
            requirement_count=len(parsed_requirements.requirements),
        )
    ):
        pool = ThreadPool(processes=max_threads)
        try:
            download_results = tuple(
                zip(
                    downloadable_artifacts,
                    pool.map(
                        functools.partial(catch, download_manager.store_downloadable_artifact),
                        downloadable_artifacts,
                    ),
                )
            )
        finally:
            pool.close()
            pool.join()

    with TRACER.timed("Categorizing {} downloaded artifacts".format(len(download_results))):
        downloaded_artifacts = {}
        download_errors = OrderedDict()
        for downloadable_artifact, download_result in download_results:
            if isinstance(download_result, DownloadedArtifact):
                downloaded_artifacts[downloadable_artifact] = download_result
            else:
                download_errors[downloadable_artifact] = download_result

        if download_errors:
            error_count = len(download_errors)
            return Error(
                "There {were} {count} {errors} downloading required artifacts:\n"
                "{error_details}".format(
                    were="was" if error_count == 1 else "were",
                    count=error_count,
                    errors=pluralize(download_errors, "error"),
                    error_details="\n".join(
                        "{index}. {pin} from {url}\n    {error}".format(
                            index=index,
                            pin=downloadable_artifact.pin,
                            url=downloadable_artifact.artifact.url,
                            error=error,
                        )
                        for index, (downloadable_artifact, error) in enumerate(
                            download_errors.items(), start=1
                        )
                    ),
                )
            )

        build_requests = []
        install_requests = []
        for target, artifacts in downloadable_artifacts_by_target.items():
            for downloadable_artifact in artifacts:
                downloaded_artifact = downloaded_artifacts[downloadable_artifact]
                if downloaded_artifact.path.endswith(".whl"):
                    install_requests.append(
                        InstallRequest(
                            target=target,
                            wheel_path=downloaded_artifact.path,
                            fingerprint=downloaded_artifact.fingerprint(),
                        )
                    )
                else:
                    build_requests.append(
                        BuildRequest(
                            target=target,
                            source_path=downloaded_artifact.path,
                            fingerprint=downloaded_artifact.fingerprint(),
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
            direct_requirements=parsed_requirements.parsed_requirements,
            package_index_configuration=PackageIndexConfiguration.create(
                resolver_version=resolver_version,
                indexes=indexes,
                find_links=find_links,
                network_configuration=network_configuration,
            ),
            cache=cache,
            compile=compile,
            prefer_older_binary=prefer_older_binary,
            use_pep517=use_pep517,
            build_isolation=build_isolation,
            verify_wheels=verify_wheels,
        )
        installed_distributions = build_and_install_request.install_distributions(
            # This otherwise checks that resolved distributions all meet internal requirement
            # constraints (This allows pip-legacy-resolver resolves with invalid solutions to be
            # failed post-facto by Pex at PEX build time). We've already done this via
            # `LockedResolve.resolve` above and need not waste time (~O(100ms)) doing this again.
            ignore_errors=True,
            max_parallel_jobs=max_parallel_jobs,
        )
    return Installed(installed_distributions=tuple(installed_distributions))
