# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import json
import os
import re
from collections import OrderedDict, defaultdict

from pex import hashing
from pex.common import safe_mkdtemp
from pex.compatibility import urlparse
from pex.dist_metadata import ProjectNameAndVersion, Requirement
from pex.hashing import Sha256
from pex.orderedset import OrderedSet
from pex.pep_440 import Version
from pex.pip import foreign_platform
from pex.pip.download_observer import Patch, PatchSet
from pex.pip.local_project import digest_local_project
from pex.pip.log_analyzer import LogAnalyzer
from pex.pip.vcs import fingerprint_downloaded_vcs_archive
from pex.pip.version import PipVersionValue
from pex.requirements import ArchiveScheme, VCSRequirement, VCSScheme
from pex.resolve.locked_resolve import LockConfiguration, LockStyle, TargetSystem
from pex.resolve.pep_691.fingerprint_service import FingerprintService
from pex.resolve.pep_691.model import Endpoint
from pex.resolve.resolved_requirement import (
    ArtifactURL,
    Fingerprint,
    PartialArtifact,
    Pin,
    ResolvedRequirement,
)
from pex.resolve.resolvers import Resolver
from pex.targets import Target
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import DefaultDict, Dict, Iterable, Mapping, Optional, Pattern, Set, Text, Tuple

    import attr  # vendor:skip

    from pex.requirements import ParsedRequirement
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class LockResult(object):
    resolved_requirements = attr.ib()  # type: Tuple[ResolvedRequirement, ...]
    local_projects = attr.ib()  # type: Tuple[str, ...]


@attr.s(frozen=True)
class Credentials(object):
    username = attr.ib()  # type: str
    password = attr.ib(default=None)  # type: Optional[str]

    def are_redacted(self):
        # type: () -> bool

        # N.B.: Pip redacts here: pex/vendor/_vendored/pip/pip/_internal/utils/misc.py
        return "****" in (self.username, self.password)

    def render_basic_auth(self):
        # type: () -> str
        if self.password is not None:
            return "{username}:{password}".format(username=self.username, password=self.password)
        return self.username


@attr.s(frozen=True)
class Netloc(object):
    host = attr.ib()  # type: str
    port = attr.ib(default=None)  # type: Optional[int]

    def render_host_port(self):
        # type: () -> str
        if self.port is not None:
            return "{host}:{port}".format(host=self.host, port=self.port)
        return self.host


@attr.s(frozen=True)
class CredentialedURL(object):
    @classmethod
    def parse(cls, url):
        # type: (Text) -> CredentialedURL

        url_info = urlparse.urlparse(url)

        # The netloc component of the parsed url combines username, password, host and port. We need
        # to track username and password; so we break up netloc into its four components.
        credentials = (
            Credentials(username=url_info.username, password=url_info.password)
            if url_info.username
            else None
        )

        netloc = Netloc(host=url_info.hostname, port=url_info.port) if url_info.hostname else None

        return cls(
            scheme=url_info.scheme,
            credentials=credentials,
            netloc=netloc,
            path=url_info.path,
            params=url_info.params,
            query=url_info.query,
            fragment=url_info.fragment,
        )

    scheme = attr.ib()  # type: str
    credentials = attr.ib()  # type: Optional[Credentials]
    netloc = attr.ib()  # type: Optional[Netloc]
    path = attr.ib()  # type: str
    params = attr.ib()  # type: str
    query = attr.ib()  # type: str
    fragment = attr.ib()  # type: str

    @property
    def has_redacted_credentials(self):
        # type: () -> bool
        if self.credentials is None:
            return False
        return self.credentials.are_redacted()

    def strip_credentials(self):
        # type: () -> CredentialedURL
        return attr.evolve(self, credentials=None)

    def strip_params_query_and_fragment(self):
        # type: () -> CredentialedURL
        return attr.evolve(self, params="", query="", fragment="")

    def inject_credentials(self, credentials):
        # type: (Optional[Credentials]) -> CredentialedURL
        return attr.evolve(self, credentials=credentials)

    def __str__(self):
        # type: () -> str

        netloc = ""
        if self.netloc is not None:
            host_port = self.netloc.render_host_port()
            netloc = (
                "{credentials}@{host_port}".format(
                    credentials=self.credentials.render_basic_auth(), host_port=host_port
                )
                if self.credentials
                else host_port
            )

        return urlparse.urlunparse(
            (self.scheme, netloc, self.path, self.params, self.query, self.fragment)
        )


@attr.s(frozen=True)
class VCSURLManager(object):
    @staticmethod
    def _normalize_vcs_url(credentialed_url):
        # type: (CredentialedURL) -> str
        return str(credentialed_url.strip_credentials().strip_params_query_and_fragment())

    @classmethod
    def create(cls, requirements):
        # type: (Iterable[ParsedRequirement]) -> VCSURLManager

        credentials_by_normalized_url = {}  # type: Dict[str, Optional[Credentials]]
        for requirement in requirements:
            if not isinstance(requirement, VCSRequirement):
                continue
            credentialed_url = CredentialedURL.parse(requirement.url)
            vcs_url = "{vcs}+{url}".format(
                vcs=requirement.vcs, url=cls._normalize_vcs_url(credentialed_url)
            )
            credentials_by_normalized_url[vcs_url] = credentialed_url.credentials
        return cls(credentials_by_normalized_url)

    _credentials_by_normalized_url = attr.ib()  # type: Mapping[str, Optional[Credentials]]

    def normalize_url(self, url):
        # type: (str) -> str

        credentialed_url = CredentialedURL.parse(url)
        if credentialed_url.has_redacted_credentials:
            normalized_vcs_url = self._normalize_vcs_url(credentialed_url)
            credentials = self._credentials_by_normalized_url.get(normalized_vcs_url)
            if credentials is not None:
                credentialed_url = credentialed_url.inject_credentials(credentials)
        return str(credentialed_url)


class AnalyzeError(Exception):
    """Indicates an error analyzing lock data."""


@attr.s(frozen=True)
class ArtifactBuildResult(object):
    url = attr.ib()  # type: ArtifactURL
    pin = attr.ib()  # type: Pin


@attr.s(frozen=True)
class ArtifactBuildObserver(object):
    _done_building_patterns = attr.ib()  # type: Iterable[Pattern]
    _artifact_url = attr.ib()  # type: ArtifactURL

    def is_done_building(self, line):
        # type: (str) -> bool
        return any(pattern.search(line) is not None for pattern in self._done_building_patterns)

    def build_result(self, line):
        # type: (str) -> Optional[ArtifactBuildResult]

        match = re.search(
            r"Source in .+ has version (?P<version>[^\s]+), which satisfies requirement "
            r"(?P<requirement>.+) .*from {url}".format(url=re.escape(self._artifact_url.raw_url)),
            line,
        )
        if not match:
            return None

        version = Version(match.group("version"))
        requirement = Requirement.parse(match.group("requirement"))
        pin = Pin(project_name=requirement.project_name, version=version)
        return ArtifactBuildResult(url=self._artifact_url, pin=pin)


class Locker(LogAnalyzer):
    def __init__(
        self,
        target,  # type: Target
        root_requirements,  # type: Iterable[ParsedRequirement]
        resolver,  # type: Resolver
        lock_configuration,  # type: LockConfiguration
        download_dir,  # type: str
        fingerprint_service=None,  # type: Optional[FingerprintService]
        pip_version=None,  # type: Optional[PipVersionValue]
    ):
        # type: (...) -> None

        self._target = target
        self._vcs_url_manager = VCSURLManager.create(root_requirements)
        self._pip_version = pip_version
        self._resolver = resolver
        self._lock_configuration = lock_configuration
        self._download_dir = download_dir
        self._fingerprint_service = fingerprint_service or FingerprintService()

        self._saved = set()  # type: Set[Pin]
        self._selected_path_to_pin = {}  # type: Dict[str, Pin]

        self._resolved_requirements = OrderedDict()  # type: OrderedDict[Pin, ResolvedRequirement]
        self._pep_691_endpoints = set()  # type: Set[Endpoint]
        self._links = defaultdict(
            OrderedDict
        )  # type: DefaultDict[Pin, OrderedDict[ArtifactURL, PartialArtifact]]
        self._known_fingerprints = {}  # type: Dict[ArtifactURL, Fingerprint]
        self._artifact_build_observer = None  # type: Optional[ArtifactBuildObserver]
        self._local_projects = OrderedSet()  # type: OrderedSet[str]
        self._lock_result = None  # type: Optional[LockResult]

    @property
    def style(self):
        # type: () -> LockStyle.Value
        return self._lock_configuration.style

    @property
    def requires_python(self):
        # type: () -> Tuple[str, ...]
        return self._lock_configuration.requires_python

    def should_collect(self, returncode):
        # type: (int) -> bool
        return returncode == 0

    def parse_url_and_maybe_record_fingerprint(self, url):
        # type: (str) -> ArtifactURL
        artifact_url = ArtifactURL.parse(url)
        if artifact_url.fingerprint:
            self._known_fingerprints[artifact_url] = artifact_url.fingerprint
        return artifact_url

    @staticmethod
    def _extract_resolve_data(artifact_url):
        # type: (ArtifactURL) -> Tuple[Pin, PartialArtifact]

        pin = Pin.canonicalize(ProjectNameAndVersion.from_filename(artifact_url.path))
        partial_artifact = PartialArtifact(artifact_url, fingerprint=artifact_url.fingerprint)
        return pin, partial_artifact

    def _maybe_record_wheel(self, url):
        # type: (str) -> ArtifactURL
        artifact_url = self.parse_url_and_maybe_record_fingerprint(url)
        if artifact_url.is_wheel:
            pin, partial_artifact = self._extract_resolve_data(artifact_url)

            # A wheel selected in a Pip download resolve can be noted more than one time. Notably,
            # this occurs across all supported versions of Pip when an index serves re-directs.
            # We want the original wheel URL in the lock since that points to the index the user
            # selected and not the re-directed final (implementation detail) URL that may change
            # but should not affect the lock.
            #
            # See: https://github.com/pex-tool/pex/issues/2414
            #
            # Sometimes, there will be a prior URL, but it will be for a failed sdist build, in
            # which case we always want to replace.
            #
            # See: https://github.com/pex-tool/pex/issues/2519
            resolved_requirement = self._resolved_requirements.get(pin)
            if not resolved_requirement or not any(
                artifact.url.is_wheel for artifact in resolved_requirement.iter_artifacts()
            ):
                additional_artifacts = self._links[pin]
                additional_artifacts.pop(artifact_url, None)
                self._resolved_requirements[pin] = ResolvedRequirement(
                    pin=pin,
                    artifact=partial_artifact,
                    additional_artifacts=tuple(additional_artifacts.values()),
                )
                self._selected_path_to_pin[os.path.basename(artifact_url.path)] = pin
        return artifact_url

    def analyze(self, line):
        # type: (str) -> LogAnalyzer.Continue[None]

        # The log sequence for processing a resolved requirement is as follows (log lines irrelevant
        # to our purposes omitted):
        #
        #   1.)        "... Found link <url1> ..."
        #   ...
        #   1.)        "... Found link <urlN> ..."
        #   1.5. URL)  "... Looking up "<url>" in the cache"
        #   1.5. PATH) "... Processing <path> ..."
        #   2.)        "... Added <varying info ...> to build tracker ..."
        # * 3.)        Lines related to extracting metadata from <requirement> if the selected
        #              distribution is an sdist in any form (VCS, local directory, source archive).
        # * 3.5. ERR)  "... WARNING: Discarding <url> <varying info...>. Command errored out with ..."
        # * 3.5. SUC)  "... Source in <tmp> has version <version>, which satisfies requirement <requirement> from <url> ..."
        #   4.)        "... Removed <requirement> from <url> ... from build tracker ..."
        #   5.)        "... Saved <download dir>/<artifact file>

        # Although section 1.5 is always present in all supported Pip versions, the lines in sections
        # 2-4 are optionally present depending on selected artifact type (wheel vs sdist vs ...) and
        # Pip version. It is constant; however, that sections 2-4 are present in all supported Pip
        # versions when dealing with an artifact that needs to be built (sdist, VCS url or local
        # project).

        # The lines in section 3 can contain this same pattern of lines if the metadata extraction
        # proceeds via PEP-517 which recursively uses Pip to resolve build dependencies. We want to
        # ignore this recursion since a lock should only contain install requirements and not build
        # requirements (If a build proceeds differently tomorrow than today then we don't care as
        # long as the final built artifact hashes the same. In other words, we completely rely on a
        # cryptographic fingerprint for reproducibility and security guarantees from a lock).

        # The section 4 line will be present for requirements that represent either local source
        # directories or VCS requirements and can be used to learn their version.

        if self._artifact_build_observer:
            if self._artifact_build_observer.is_done_building(line):
                self._artifact_build_observer = None
                return self.Continue()

            build_result = self._artifact_build_observer.build_result(line)
            if build_result:
                artifact_url = build_result.url
                source_fingerprint = None  # type: Optional[Fingerprint]
                verified = False
                if isinstance(artifact_url.scheme, VCSScheme):
                    source_fingerprint, archive_path = fingerprint_downloaded_vcs_archive(
                        download_dir=self._download_dir,
                        project_name=str(build_result.pin.project_name),
                        version=str(build_result.pin.version),
                        vcs=artifact_url.scheme.vcs,
                    )
                    verified = True
                    selected_path = os.path.basename(archive_path)
                    artifact_url = self.parse_url_and_maybe_record_fingerprint(
                        self._vcs_url_manager.normalize_url(artifact_url.raw_url)
                    )
                    self._selected_path_to_pin[selected_path] = build_result.pin
                elif isinstance(artifact_url.scheme, ArchiveScheme.Value):
                    selected_path = os.path.basename(artifact_url.path)
                    source_archive_path = os.path.join(self._download_dir, selected_path)
                    # If Pip resolves the artifact from its own cache, we will not find it in the
                    # download dir for this run; so guard against that. In this case the existing
                    # machinery that finalizes a locks missing fingerprints will download the
                    # artifact and hash it.
                    if os.path.isfile(source_archive_path):
                        digest = Sha256()
                        hashing.file_hash(source_archive_path, digest)
                        source_fingerprint = Fingerprint.from_digest(digest)
                        verified = True
                    self._selected_path_to_pin[selected_path] = build_result.pin
                elif "file" == artifact_url.scheme:
                    digest = Sha256()
                    if os.path.isfile(artifact_url.path):
                        hashing.file_hash(artifact_url.path, digest)
                        self._selected_path_to_pin[
                            os.path.basename(artifact_url.path)
                        ] = build_result.pin
                    else:
                        digest_local_project(
                            directory=artifact_url.path,
                            digest=digest,
                            pip_version=self._pip_version,
                            target=self._target,
                            resolver=self._resolver,
                        )
                        self._local_projects.add(artifact_url.path)
                        self._saved.add(build_result.pin)
                    source_fingerprint = Fingerprint.from_digest(digest)
                    verified = True
                else:
                    raise AnalyzeError(
                        "Unexpected scheme {scheme!r} for artifact at {url}".format(
                            scheme=artifact_url.scheme, url=artifact_url
                        )
                    )

                additional_artifacts = self._links[build_result.pin]
                additional_artifacts.pop(artifact_url, None)

                self._resolved_requirements[build_result.pin] = ResolvedRequirement(
                    pin=build_result.pin,
                    artifact=PartialArtifact(
                        url=artifact_url, fingerprint=source_fingerprint, verified=verified
                    ),
                    additional_artifacts=tuple(additional_artifacts.values()),
                )
            return self.Continue()

        match = re.search(
            r"Fetched page (?P<index_url>[^\s]+) as (?P<content_type>{content_types})".format(
                content_types="|".join(
                    re.escape(content_type) for content_type in self._fingerprint_service.accept
                )
            ),
            line,
        )
        if match:
            self._pep_691_endpoints.add(
                Endpoint(url=match.group("index_url"), content_type=match.group("content_type"))
            )
            return self.Continue()

        match = re.search(r"Looking up \"(?P<url>[^\s]+)\" in the cache", line)
        if match:
            self._maybe_record_wheel(match.group("url"))

        match = re.search(r"Processing (?P<path>.*\.(whl|tar\.(gz|bz2|xz)|tgz|tbz2|txz|zip))", line)
        if match:
            self._maybe_record_wheel(
                "file://{path}".format(path=os.path.abspath(match.group("path")))
            )

        match = re.search(
            r"Added (?P<requirement>.+) from (?P<url>[^\s]+) .*to build tracker",
            line,
        )
        if match:
            raw_requirement = match.group("requirement")
            url = self._maybe_record_wheel(match.group("url"))
            if not url.is_wheel:
                self._artifact_build_observer = ArtifactBuildObserver(
                    done_building_patterns=(
                        re.compile(
                            r"Removed {requirement} from {url} (?:.* )?from build tracker".format(
                                requirement=re.escape(raw_requirement), url=re.escape(url.raw_url)
                            )
                        ),
                        re.compile(r"WARNING: Discarding {url}".format(url=re.escape(url.raw_url))),
                    ),
                    artifact_url=url,
                )
            return self.Continue()

        match = re.search(r"Added (?P<file_url>file:.+) to build tracker", line)
        if match:
            file_url = match.group("file_url")
            self._artifact_build_observer = ArtifactBuildObserver(
                done_building_patterns=(
                    re.compile(
                        r"Removed .+ from {file_url} from build tracker".format(
                            file_url=re.escape(file_url)
                        )
                    ),
                    re.compile(r"WARNING: Discarding {url}".format(url=re.escape(file_url))),
                ),
                artifact_url=self.parse_url_and_maybe_record_fingerprint(file_url),
            )
            return self.Continue()

        match = re.search(r"Saved (?P<file_path>.+)$", line)
        if match:
            saved_path = match.group("file_path")
            build_result_pin = self._selected_path_to_pin.get(os.path.basename(saved_path))
            if build_result_pin:
                self._saved.add(build_result_pin)
            return self.Continue()

        if self.style in (LockStyle.SOURCES, LockStyle.UNIVERSAL):
            match = re.search(r"Found link (?P<url>[^\s]+)(?: \(from .*\))?, version: ", line)
            if match:
                url = self.parse_url_and_maybe_record_fingerprint(match.group("url"))
                pin, partial_artifact = self._extract_resolve_data(url)
                self._links[pin][url] = partial_artifact
                return self.Continue()

        return self.Continue()

    def analysis_completed(self):
        # type: () -> None
        resolved_requirements = [
            resolved_requirement
            for resolved_requirement in self._resolved_requirements.values()
            if resolved_requirement.pin in self._saved
        ]

        artifacts = []
        for resolved_requirement in resolved_requirements:
            for artifact in resolved_requirement.iter_artifacts():
                if not artifact.fingerprint:
                    fingerprint = self._known_fingerprints.get(artifact.url)
                    if fingerprint:
                        artifact = attr.evolve(artifact, fingerprint=fingerprint)
                artifacts.append(artifact)

        fingerprinted_artifacts = {
            artifact.url: artifact
            for artifact in self._fingerprint_service.fingerprint(
                endpoints=self._pep_691_endpoints,
                artifacts=tuple(artifacts),
            )
        }

        def maybe_fill_in_fingerprints(resolved_requirement):
            # type: (ResolvedRequirement) -> ResolvedRequirement
            return attr.evolve(
                resolved_requirement,
                artifact=fingerprinted_artifacts.get(resolved_requirement.artifact.url),
                additional_artifacts=tuple(
                    fingerprinted_artifacts.get(artifact.url)
                    for artifact in resolved_requirement.additional_artifacts
                ),
            )

        self._lock_result = LockResult(
            resolved_requirements=tuple(
                maybe_fill_in_fingerprints(resolved_requirement)
                for resolved_requirement in resolved_requirements
            ),
            local_projects=tuple(self._local_projects),
        )

    @property
    def lock_result(self):
        # type: () -> LockResult
        assert (
            self._lock_result is not None
        ), "Lock result was retrieved before analysis was complete."
        return self._lock_result


# See https://www.python.org/dev/peps/pep-0508/#environment-markers for more about these values.
_OS_NAME = {
    TargetSystem.LINUX: "posix",
    TargetSystem.MAC: "posix",
    TargetSystem.WINDOWS: "nt",
}
_PLATFORM_SYSTEM = {
    TargetSystem.LINUX: "Linux",
    TargetSystem.MAC: "Darwin",
    TargetSystem.WINDOWS: "Windows",
}
_SYS_PLATFORMS = {
    TargetSystem.LINUX: ("linux", "linux2"),
    TargetSystem.MAC: ("darwin",),
    TargetSystem.WINDOWS: ("win32",),
}

# See: https://peps.python.org/pep-0425/#platform-tag for more about the wheel platform tag.
_PLATFORM_TAG_REGEXP = {
    TargetSystem.LINUX: r"linux",
    TargetSystem.MAC: r"macosx",
    TargetSystem.WINDOWS: r"win",
}


def patch(lock_configuration):
    # type: (LockConfiguration) -> PatchSet

    if lock_configuration.style != LockStyle.UNIVERSAL:
        return PatchSet()

    patches_dir = safe_mkdtemp()
    patches = []
    if lock_configuration.requires_python:
        patches.append(
            foreign_platform.patch_requires_python(
                requires_python=lock_configuration.requires_python, patches_dir=patches_dir
            )
        )

    env = {}  # type: Dict[str, str]
    if lock_configuration.target_systems and set(lock_configuration.target_systems) != set(
        TargetSystem.values()
    ):
        target_systems = {
            "os_names": [
                _OS_NAME[target_system] for target_system in lock_configuration.target_systems
            ],
            "platform_systems": [
                _PLATFORM_SYSTEM[target_system]
                for target_system in lock_configuration.target_systems
            ],
            "sys_platforms": list(
                itertools.chain.from_iterable(
                    _SYS_PLATFORMS[target_system]
                    for target_system in lock_configuration.target_systems
                )
            ),
            "platform_tag_regexps": [
                _PLATFORM_TAG_REGEXP[target_system]
                for target_system in lock_configuration.target_systems
            ],
        }
        with open(os.path.join(patches_dir, "target_systems.json"), "w") as fp:
            json.dump(target_systems, fp)
        env.update(_PEX_TARGET_SYSTEMS_FILE=fp.name)

    patches.append(Patch.from_code_resource(__name__, "locker_patches.py", **env))

    return PatchSet(patches=tuple(patches))
