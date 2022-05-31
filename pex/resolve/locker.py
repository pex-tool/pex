# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os
import pkgutil
import re
from collections import defaultdict

from pex.common import safe_mkdtemp
from pex.compatibility import unquote, urlparse
from pex.dist_metadata import ProjectNameAndVersion, Requirement
from pex.interpreter_constraints import iter_compatible_versions
from pex.orderedset import OrderedSet
from pex.pep_440 import Version
from pex.pip.download_observer import DownloadObserver, Patch
from pex.pip.local_project import fingerprint_local_project
from pex.pip.log_analyzer import LogAnalyzer
from pex.pip.vcs import fingerprint_downloaded_vcs_archive
from pex.requirements import VCS, VCSScheme, parse_scheme
from pex.resolve.locked_resolve import LockConfiguration, LockStyle
from pex.resolve.resolved_requirement import Fingerprint, PartialArtifact, Pin, ResolvedRequirement
from pex.resolve.resolvers import Resolver
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import DefaultDict, Dict, List, Optional, Pattern, Set, Text, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class _VCSPartialInfo(object):
    vcs = attr.ib()  # type: VCS.Value
    via = attr.ib()  # type: Tuple[str, ...]


@attr.s(frozen=True)
class LockResult(object):
    resolved_requirements = attr.ib()  # type: Tuple[ResolvedRequirement, ...]
    local_projects = attr.ib()  # type: Tuple[str, ...]


class Locker(LogAnalyzer):
    def __init__(
        self,
        resolver,  # type: Resolver
        lock_configuration,  # type: LockConfiguration
        download_dir,  # type: str
    ):
        # type: (...) -> None
        self._resolver = resolver
        self._lock_configuration = lock_configuration
        self._download_dir = download_dir

        self._saved = set()  # type: Set[Pin]

        self._resolved_requirements = []  # type: List[ResolvedRequirement]
        self._links = defaultdict(OrderedSet)  # type: DefaultDict[Pin, OrderedSet[PartialArtifact]]
        self._done_building_re = None  # type: Optional[Pattern]
        self._source_built_re = None  # type: Optional[Pattern]
        self._local_projects = OrderedSet()  # type: OrderedSet[str]
        self._vcs_partial_info = None  # type: Optional[_VCSPartialInfo]
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
    def _extract_resolve_data(url):
        # type: (str) -> Tuple[Pin, PartialArtifact]

        fingerprint = None  # type: Optional[Fingerprint]
        fingerprint_match = re.search(r"(?P<url>[^#]+)#(?P<algorithm>[^=]+)=(?P<hash>.*)$", url)
        if fingerprint_match:
            url = fingerprint_match.group("url")
            algorithm = fingerprint_match.group("algorithm")
            hash_ = fingerprint_match.group("hash")
            fingerprint = Fingerprint(algorithm=algorithm, hash=hash_)

        pin = Pin.canonicalize(
            ProjectNameAndVersion.from_filename(unquote(urlparse.urlparse(url).path))
        )
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
            elif self._vcs_partial_info is not None:
                match = re.search(
                    r"Source in .+ has version (?P<version>[^\s]+), which satisfies requirement "
                    r"(?P<requirement>.+) from (?P<url>[^\s]+)(?: \(from .+)?$",
                    line,
                )
                if match:
                    vcs_partial_info = self._vcs_partial_info
                    self._vcs_partial_info = None

                    raw_requirement = match.group("requirement")
                    requirement = Requirement.parse(raw_requirement)
                    version = match.group("version")

                    # VCS requirements are satisfied by a singular source; so we need not consult
                    # links collected in this round.
                    self._resolved_requirements.append(
                        ResolvedRequirement(
                            requirement=requirement,
                            pin=Pin(
                                project_name=requirement.project_name, version=Version(version)
                            ),
                            artifact=PartialArtifact(
                                url=match.group("url"),
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
                digest = fingerprint_local_project(local_project_path, self._resolver)
                self._local_projects.add(local_project_path)
                self._resolved_requirements.append(
                    ResolvedRequirement(
                        requirement=requirement,
                        pin=pin,
                        artifact=PartialArtifact(
                            url=file_url,
                            fingerprint=Fingerprint(algorithm=digest.algorithm, hash=digest),
                            verified=True,
                        ),
                    )
                )
                self._saved.add(pin)
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
                project_name_and_version, partial_artifact = self._extract_resolve_data(url)

                additional_artifacts = self._links[project_name_and_version]
                additional_artifacts.discard(partial_artifact)

                self._resolved_requirements.append(
                    ResolvedRequirement(
                        requirement=requirement,
                        pin=project_name_and_version,
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
            self._saved.add(
                Pin.canonicalize(
                    ProjectNameAndVersion.from_filename(os.path.basename(match.group("file_path")))
                )
            )
            return self.Continue()

        if self.style in (LockStyle.SOURCES, LockStyle.UNIVERSAL):
            match = re.search(r"Found link (?P<url>[^\s]+)(?: \(from .*\))?, version: ", line)
            if match:
                project_name_and_version, partial_artifact = self._extract_resolve_data(
                    match.group("url")
                )
                self._links[project_name_and_version].add(partial_artifact)
                return self.Continue()

        if LockStyle.UNIVERSAL == self.style:
            match = re.search(
                r"Skipping link: none of the wheel's tags \([^)]+\) are compatible "
                r"\(run pip debug --verbose to show compatible tags\): "
                r"(?P<url>[^\s]+) ",
                line,
            )
            if match:
                project_name_and_version, partial_artifact = self._extract_resolve_data(
                    match.group("url")
                )
                self._links[project_name_and_version].add(partial_artifact)

        return self.Continue()

    def analysis_completed(self):
        # type: () -> None
        self._lock_result = LockResult(
            resolved_requirements=tuple(
                resolved_requirement
                for resolved_requirement in self._resolved_requirements
                if resolved_requirement.pin in self._saved
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


def patch(
    resolver,  # type: Resolver
    lock_configuration,  # type: LockConfiguration
    download_dir,  # type: str
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

    return DownloadObserver(
        analyzer=Locker(
            resolver=resolver, lock_configuration=lock_configuration, download_dir=download_dir
        ),
        patch=Patch(code=code, env=env),
    )
