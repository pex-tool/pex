# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import json
import os
import pkgutil
import re
from collections import defaultdict

from pex import hashing
from pex.common import safe_mkdtemp
from pex.compatibility import unquote, urlparse
from pex.dist_metadata import ProjectNameAndVersion, Requirement, UnrecognizedDistributionFormat
from pex.hashing import Sha256
from pex.interpreter_constraints import iter_compatible_versions
from pex.orderedset import OrderedSet
from pex.pep_440 import Version
from pex.pip.download_observer import DownloadObserver, Patch
from pex.pip.local_project import digest_local_project, fingerprint_local_project
from pex.pip.log_analyzer import LogAnalyzer
from pex.pip.vcs import fingerprint_downloaded_vcs_archive
from pex.pip.version import PipVersionValue
from pex.requirements import VCS, VCSRequirement, VCSScheme, parse_scheme
from pex.resolve.locked_resolve import LockConfiguration, LockStyle, TargetSystem
from pex.resolve.pep_691.fingerprint_service import FingerprintService
from pex.resolve.pep_691.model import Endpoint
from pex.resolve.resolved_requirement import Fingerprint, PartialArtifact, Pin, ResolvedRequirement
from pex.resolve.resolvers import Resolver
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import (
        DefaultDict,
        Dict,
        Iterable,
        List,
        Mapping,
        Optional,
        Pattern,
        Set,
        Text,
        Tuple,
    )

    import attr  # vendor:skip

    from pex.requirements import ParsedRequirement
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class _VCSPartialInfo(object):
    vcs = attr.ib()  # type: VCS.Value
    via = attr.ib()  # type: Tuple[str, ...]


@attr.s(frozen=True)
class _SourceDistributionPartialInfo(object):
    url = attr.ib()  # type: str
    partial_artifact = attr.ib()  # type: PartialArtifact


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


class Locker(LogAnalyzer):
    def __init__(
        self,
        root_requirements,  # type: Iterable[ParsedRequirement]
        pip_version,  # type: PipVersionValue
        resolver,  # type: Resolver
        lock_configuration,  # type: LockConfiguration
        download_dir,  # type: str
        fingerprint_service=None,  # type: Optional[FingerprintService]
    ):
        # type: (...) -> None

        self._vcs_url_manager = VCSURLManager.create(root_requirements)
        self._pip_version = pip_version
        self._resolver = resolver
        self._lock_configuration = lock_configuration
        self._download_dir = download_dir
        self._fingerprint_service = fingerprint_service or FingerprintService()

        self._saved = set()  # type: Set[Pin]

        self._resolved_requirements = []  # type: List[ResolvedRequirement]
        self._pep_691_endpoints = set()  # type: Set[Endpoint]
        self._links = defaultdict(OrderedSet)  # type: DefaultDict[Pin, OrderedSet[PartialArtifact]]
        self._done_building_re = None  # type: Optional[Pattern]
        self._source_built_re = None  # type: Optional[Pattern]
        self._local_projects = OrderedSet()  # type: OrderedSet[str]
        self._vcs_partial_info = None  # type: Optional[_VCSPartialInfo]
        self._source_distribution_partial_artifact = None  # type: Optional[PartialArtifact]
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

    @staticmethod
    def _try_extract_pin(filename):
        # type: (str) -> Optional[Pin]
        try:
            return Pin.canonicalize(ProjectNameAndVersion.from_filename(filename))
        except UnrecognizedDistributionFormat:
            # A non-wheel path could be a proper sdist (.tar.gz or .zip), or it could just be an
            # archive of a source project following no naming convention at all. In either case Pip
            # will need to gather metadata by building or partially building the distribution, and
            # we can scrape the logs for the results of that later to get the project name and
            # version robustly and exactly as Pip sees it.
            return None

    @classmethod
    def _extract_resolve_data(cls, url):
        # type: (str) -> Tuple[Optional[Pin], PartialArtifact]

        fingerprint = None  # type: Optional[Fingerprint]
        fingerprint_match = re.search(r"(?P<url>[^#]+)#(?P<algorithm>[^=]+)=(?P<hash>.*)$", url)
        if fingerprint_match:
            url = fingerprint_match.group("url")
            algorithm = fingerprint_match.group("algorithm")
            hash_ = fingerprint_match.group("hash")
            fingerprint = Fingerprint(algorithm=algorithm, hash=hash_)

        pin = cls._try_extract_pin(unquote(urlparse.urlparse(url).path))
        partial_artifact = PartialArtifact(url, fingerprint)
        return pin, partial_artifact

    def analyze(self, line):
        # type: (str) -> LogAnalyzer.Continue[None]

        # The log sequence for processing a resolved requirement is as follows (log lines irrelevant
        # to our purposes omitted):
        #
        #   1.) "... Found link <url1> ..."
        #   ...
        #   1.) "... Found link <urlN> ..."
        #   2.) "... Added <varying info ...> to build tracker ..."
        #   3.) Lines related to extracting metadata from <requirement>'s artifact
        # * 4.) "... Source in <tmp> has version <version>, which satisfies requirement "
        #       "<requirement> from <url> ..."
        #   5.) "... Removed <requirement> from <url> ... from build tracker ..."
        #   6.) "... Saved <download dir>/<artifact file>

        # The lines in section 3 can contain this same pattern of lines if the metadata extraction
        # proceeds via PEP-517 which recursively uses Pip to resolve build dependencies. We want to
        # ignore this recursion since a lock should only contain install requirements and not build
        # requirements (If a build proceeds differently tomorrow than today then we don't care as
        # long as the final built artifact hashes the same. In other words, we completely rely on a
        # cryptographic fingerprint for reproducibility and security guarantees from a lock).

        # The section 4 line will be present for requirements that represent either local source
        # directories or VCS requirements and can be used to learn their version.

        if self._done_building_re:
            if self._done_building_re.search(line):
                self._done_building_re = None
            elif (
                self._vcs_partial_info is not None
                or self._source_distribution_partial_artifact is not None
            ):
                match = re.search(
                    r"Source in .+ has version (?P<version>[^\s]+), which satisfies requirement "
                    r"(?P<requirement>.+) from (?P<url>[^\s]+)(?: \(from .+)?$",
                    line,
                )
                if match:
                    raw_requirement = match.group("requirement")
                    requirement = Requirement.parse(raw_requirement)
                    version = match.group("version")
                    pin = Pin(project_name=requirement.project_name, version=Version(version))
                    self._saved.add(pin)

                    if self._vcs_partial_info:
                        vcs_partial_info = self._vcs_partial_info
                        self._vcs_partial_info = None

                        # VCS requirements are satisfied by a singular source; so we need not
                        # consult links collected in this round.
                        self._resolved_requirements.append(
                            ResolvedRequirement(
                                requirement=requirement,
                                pin=pin,
                                artifact=PartialArtifact(
                                    url=self._vcs_url_manager.normalize_url(match.group("url")),
                                    fingerprint=fingerprint_downloaded_vcs_archive(
                                        download_dir=self._download_dir,
                                        project_name=str(requirement.project_name),
                                        version=version,
                                        vcs=vcs_partial_info.vcs,
                                    ),
                                    verified=True,
                                ),
                                via=vcs_partial_info.via,
                            )
                        )
                    elif self._source_distribution_partial_artifact:
                        partial_artifact = self._source_distribution_partial_artifact
                        self._source_distribution_partial_artifact = None

                        url_info = urlparse.urlparse(partial_artifact.url)
                        source_distribution_path = unquote(url_info.path)
                        if "file" != url_info.scheme:
                            source_distribution_path = os.path.join(
                                self._download_dir,
                                os.path.basename(source_distribution_path),
                            )
                        if not os.path.exists(source_distribution_path):
                            raise AnalyzeError(
                                "Failed to lock {artifact}. Could not obtain its content for "
                                "analysis.".format(artifact=partial_artifact)
                            )

                        digest = Sha256()
                        if os.path.isdir(source_distribution_path):
                            digest_local_project(
                                directory=source_distribution_path,
                                digest=digest,
                                pip_version=self._pip_version,
                                resolver=self._resolver,
                            )
                        else:
                            hashing.file_hash(source_distribution_path, digest)
                        fingerprint = digest.hexdigest()  # type: hashing.Fingerprint

                        self._resolved_requirements.append(
                            ResolvedRequirement(
                                requirement=requirement,
                                pin=pin,
                                artifact=attr.evolve(
                                    partial_artifact,
                                    fingerprint=Fingerprint(
                                        algorithm=fingerprint.algorithm, hash=fingerprint
                                    ),
                                    verified=True,
                                ),
                            )
                        )

            return self.Continue()

        if self._source_built_re:
            match = self._source_built_re.search(line)
            if match:
                raw_requirement = match.group("requirement")
                file_url = match.group("file_url")
                self._done_building_re = re.compile(
                    r"Removed {requirement} from {file_url} (?:.* )?from build tracker".format(
                        requirement=re.escape(raw_requirement), file_url=re.escape(file_url)
                    )
                )
                self._source_built_re = None

                requirement = Requirement.parse(raw_requirement)
                version = match.group("version")

                pin = Pin(project_name=requirement.project_name, version=Version(version))

                local_project_path = urlparse.urlparse(file_url).path
                fingerprint = fingerprint_local_project(
                    local_project_path, self._pip_version, self._resolver
                )
                self._local_projects.add(local_project_path)
                self._resolved_requirements.append(
                    ResolvedRequirement(
                        requirement=requirement,
                        pin=pin,
                        artifact=PartialArtifact(
                            url=file_url,
                            fingerprint=Fingerprint(
                                algorithm=fingerprint.algorithm, hash=fingerprint
                            ),
                            verified=True,
                        ),
                    )
                )
                self._saved.add(pin)
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

        match = re.search(
            r"Added (?P<requirement>.+) from (?P<url>[^\s]+) (?:\(from (?P<from>.*)\) )?to build "
            r"tracker",
            line,
        )
        if match:
            raw_requirement = match.group("requirement")
            url = match.group("url")
            self._done_building_re = re.compile(
                r"Removed {requirement} from {url} (?:.* )?from build tracker".format(
                    requirement=re.escape(raw_requirement), url=re.escape(url)
                )
            )

            from_ = match.group("from")
            if from_:
                via = tuple(from_.split("->"))
            else:
                via = ()

            parsed_scheme = parse_scheme(urlparse.urlparse(url).scheme)
            if isinstance(parsed_scheme, VCSScheme):
                # We'll get the remaining information we need to record the resolved VCS requirement
                # in a later log line; so just save what we have so far.
                self._vcs_partial_info = _VCSPartialInfo(vcs=parsed_scheme.vcs, via=via)
            else:
                requirement = Requirement.parse(raw_requirement)
                maybe_pin, partial_artifact = self._extract_resolve_data(url)
                if maybe_pin is None:
                    self._source_distribution_partial_artifact = partial_artifact
                    return self.Continue()

                additional_artifacts = self._links[maybe_pin]
                additional_artifacts.discard(partial_artifact)

                self._resolved_requirements.append(
                    ResolvedRequirement(
                        requirement=requirement,
                        pin=maybe_pin,
                        artifact=partial_artifact,
                        additional_artifacts=tuple(additional_artifacts),
                        via=via,
                    )
                )
            return self.Continue()

        match = re.search(r"Added (?P<file_url>file:.+) to build tracker", line)
        if match:
            file_url = match.group("file_url")
            self._source_built_re = re.compile(
                r"Source in .+ has version (?P<version>.+), which satisfies requirement "
                r"(?P<requirement>.+) from (?P<file_url>{file_url})".format(
                    file_url=re.escape(file_url)
                )
            )
            return self.Continue()

        match = re.search(r"Saved (?P<file_path>.+)$", line)
        if match:
            maybe_pin = self._try_extract_pin(os.path.basename(match.group("file_path")))
            if maybe_pin:
                self._saved.add(maybe_pin)
            return self.Continue()

        if self.style in (LockStyle.SOURCES, LockStyle.UNIVERSAL):
            match = re.search(r"Found link (?P<url>[^\s]+)(?: \(from .*\))?, version: ", line)
            if match:
                url = match.group("url")
                maybe_pin, partial_artifact = self._extract_resolve_data(url)
                if not maybe_pin:
                    self._source_distribution_partial_artifact = partial_artifact
                    return self.Continue()

                self._links[maybe_pin].add(partial_artifact)
                return self.Continue()

        return self.Continue()

    def analysis_completed(self):
        # type: () -> None
        resolved_requirements = [
            resolved_requirement
            for resolved_requirement in self._resolved_requirements
            if resolved_requirement.pin in self._saved
        ]

        fingerprinted_artifacts = {
            artifact.url: artifact
            for artifact in self._fingerprint_service.fingerprint(
                endpoints=self._pep_691_endpoints,
                artifacts=tuple(
                    artifact
                    for resolved_requirement in resolved_requirements
                    for artifact in resolved_requirement.iter_artifacts()
                ),
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


def patch(
    root_requirements,  # type: Iterable[ParsedRequirement]
    pip_version,  # type: PipVersionValue
    resolver,  # type: Resolver
    lock_configuration,  # type: LockConfiguration
    download_dir,  # type: str
    fingerprint_service=None,  # type: Optional[FingerprintService]
):
    # type: (...) -> DownloadObserver[Locker]

    code = None  # type: Optional[Text]
    env = {}  # type: Dict[str, str]

    if lock_configuration.style == LockStyle.UNIVERSAL:
        code_bytes = pkgutil.get_data(__name__, "locker_patches.py")
        assert code_bytes is not None, (
            "The sibling resource locker_patches.py of {} should always be present in a Pex "
            "distribution or source tree.".format(__name__)
        )
        code = code_bytes.decode("utf-8")

        if lock_configuration.requires_python:
            version_info_dir = safe_mkdtemp()
            with TRACER.timed(
                "Calculating compatible python versions for {requires_python}".format(
                    requires_python=lock_configuration.requires_python
                )
            ):
                python_full_versions = list(
                    iter_compatible_versions(lock_configuration.requires_python)
                )
                with open(os.path.join(version_info_dir, "python_full_versions.json"), "w") as fp:
                    json.dump(python_full_versions, fp)
                env.update(_PEX_PYTHON_VERSIONS_FILE=fp.name)

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
            target_systems_info_dir = safe_mkdtemp()
            with open(os.path.join(target_systems_info_dir, "target_systems.json"), "w") as fp:
                json.dump(target_systems, fp)
            env.update(_PEX_TARGET_SYSTEMS_FILE=fp.name)

    return DownloadObserver(
        analyzer=Locker(
            root_requirements=root_requirements,
            pip_version=pip_version,
            resolver=resolver,
            lock_configuration=lock_configuration,
            download_dir=download_dir,
            fingerprint_service=fingerprint_service,
        ),
        patch=Patch(code=code, env=env),
    )
