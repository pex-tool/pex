# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import sys
from collections import OrderedDict, defaultdict, deque

from pex import toml
from pex.artifact_url import RANKED_ALGORITHMS, VCS, ArtifactURL, Fingerprint, VCSScheme
from pex.common import pluralize
from pex.compatibility import text, urlparse
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import Constraint, Requirement
from pex.exceptions import production_assert
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pep_425 import CompatibilityTags, RankedTag
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.requirements import LocalProjectRequirement, URLRequirement, parse_requirement_string
from pex.resolve.locked_resolve import (
    DownloadableArtifact,
    FileArtifact,
    LocalProjectArtifact,
    LockedRequirement,
    LockedResolve,
    Resolved,
    TargetSystem,
    UnFingerprintedLocalProjectArtifact,
    UnFingerprintedVCSArtifact,
    VCSArtifact,
)
from pex.resolve.lockfile.requires_dist import remove_unused_requires_dist
from pex.resolve.lockfile.subset import Subset, SubsetResult
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolved_requirement import Pin
from pex.resolve.resolver_configuration import BuildConfiguration
from pex.result import Error, ResultError, try_
from pex.sorted_tuple import SortedTuple
from pex.targets import Target, Targets
from pex.third_party.packaging.markers import InvalidMarker, Marker
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.toml import InlineTable, TomlDecodeError
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import (
        IO,
        Any,
        DefaultDict,
        Dict,
        FrozenSet,
        Iterable,
        Iterator,
        List,
        Mapping,
        Optional,
        Sequence,
        Set,
        Text,
        Tuple,
        Type,
        TypeVar,
        Union,
    )

    import attr  # vendor:skip

    from pex.requirements import ParsedRequirement
else:
    from pex.third_party import attr


def _calculate_marker(
    project_name,  # type: ProjectName
    dependants_by_project_name,  # type: Mapping[ProjectName, OrderedSet[Tuple[ProjectName, Optional[Marker]]]]
):
    # type: (...) -> Optional[Marker]

    dependants = dependants_by_project_name.get(project_name)
    if not dependants:
        return None

    # We make a very basic effort at de-duplication by storing markers as strings in (ordered) sets.
    # TODO: Perform post-processing on the calculated Marker that does proper logic reduction; e.g:
    #  python_version >= '3.9' and python_version == '3.11.*' -> python_version == '3.11.*'

    or_markers = OrderedSet()  # type: OrderedSet[str]
    for dependant_project_name, marker in dependants:
        and_markers = OrderedSet()  # type: OrderedSet[str]
        if marker:
            and_markers.add(str(marker))
        guard_marker = _calculate_marker(dependant_project_name, dependants_by_project_name)
        if guard_marker:
            and_markers.add(str(guard_marker))

        if not and_markers:
            # This indicates a dependency path that is not conditioned by any markers; i.e.:
            # `project_name` is always required by this dependency path; trumping all others.
            return None

        if len(and_markers) == 1:
            or_markers.add(and_markers.pop())
        else:
            or_markers.add("({anded})".format(anded=") and (".join(and_markers)))

    if not or_markers:
        # No dependency path was conditioned by any marker at all; so `project_name` is always
        # strongly reachable.
        return None

    if len(or_markers) == 1:
        return Marker(or_markers.pop())

    return Marker("({ored})".format(ored=") or (".join(or_markers)))


_MARKER_CONJUNCTIONS = ("and", "or")


def _process_marker_list(marker_list):
    # type: (List[Any]) -> List[Any]

    reduced_markers = []  # type: List[Any]

    for expression in marker_list:
        if isinstance(expression, list):
            reduced = _process_marker_list(expression)
            if reduced:
                reduced_markers.append(reduced)
        elif isinstance(expression, tuple):
            lhs, op, rhs = expression
            if lhs.value == "extra" or rhs.value == "extra":
                continue
            reduced_markers.append(expression)
        else:
            assert expression in _MARKER_CONJUNCTIONS
            if reduced_markers:
                # A conjunction is only needed if there is a LHS and a RHS. We can check the LHS
                # now.
                reduced_markers.append(expression)

    # And we can now make sure conjunctions have a RHS.
    if reduced_markers and reduced_markers[-1] in _MARKER_CONJUNCTIONS:
        reduced_markers.pop()

    return reduced_markers


def _elide_extras(marker):
    # type: (Marker) -> Optional[Marker]

    # When a lock is created, its input requirements may include extras and that causes certain
    # extra requirements to be included in the lock. When converting that lock, the extras have been
    # sealed in already; so any extra markers should be ignored; so we elide them from all marker
    # expressions.

    markers = _process_marker_list(marker._markers)
    if not markers:
        return None

    marker._markers = markers
    return marker


def _to_environment(system):
    # type: (TargetSystem.Value) -> str
    if system is TargetSystem.LINUX:
        return "platform_system == 'Linux'"
    elif system is TargetSystem.MAC:
        return "platform_system == 'Darwin'"
    else:
        production_assert(system is TargetSystem.WINDOWS)
        return "platform_system == 'Windows'"


def convert(
    root_requirements,  # type: Iterable[Requirement]
    locked_resolve,  # type: LockedResolve
    output,  # type: IO[bytes]
    requires_python=None,  # type: Optional[str]
    target_systems=(),  # type: Iterable[TargetSystem.Value]
    subset=(),  # type: Iterable[DownloadableArtifact]
    include_dependency_info=True,  # type bool
):
    # type: (...) -> None

    locked_resolve = remove_unused_requires_dist(
        resolve_requirements=root_requirements,
        locked_resolve=locked_resolve,
        requires_python=[requires_python] if requires_python else [],
        target_systems=target_systems,
    )

    pylock = OrderedDict()  # type: OrderedDict[str, Any]
    pylock["lock-version"] = "1.0"  # https://peps.python.org/pep-0751/#lock-version

    if target_systems:
        # https://peps.python.org/pep-0751/#environments
        #
        # TODO: We just stick to mapping `--target-system` into markers currently but this should
        #  probably include the full marker needed to rule out invalid installs, like Python 2.7
        #  attempting to install a lock with only Python 3 wheels.
        pylock["environments"] = sorted(_to_environment(system) for system in target_systems)
    if requires_python:
        # https://peps.python.org/pep-0751/#requires-python
        #
        # TODO: This is currently just the `--interpreter-constraint` for `--style universal` locks
        #  but it should probably be further refined (or purely calculated for non universal locks)
        #  from locked project requires-python values and even more narrowly by locked projects with
        #  only wheel artifacts by the wheel tags.
        pylock["requires-python"] = requires_python

    # TODO: These 3 assume a `pyproject.toml` is the input source for the lock. It almost never is
    #  for current Pex lock use cases. Figure out if there is anything better that can be done.
    pylock["extras"] = []  # https://peps.python.org/pep-0751/#extras
    pylock["dependency-groups"] = []  # https://peps.python.org/pep-0751/#dependency-groups
    pylock["default-groups"] = []  # https://peps.python.org/pep-0751/#default-groups

    pylock["created-by"] = "pex"  # https://peps.python.org/pep-0751/#created-by

    artifact_subset_by_pin = defaultdict(
        list
    )  # type: DefaultDict[Pin, List[Union[FileArtifact, LocalProjectArtifact, UnFingerprintedLocalProjectArtifact, UnFingerprintedVCSArtifact, VCSArtifact]]]
    for downloadable_artifact in subset:
        production_assert(
            downloadable_artifact.version is not None,
            "Pex locks should always have pins for all downloaded artifacts.",
        )
        pin = Pin(
            project_name=downloadable_artifact.project_name,
            version=cast(Version, downloadable_artifact.version),
        )
        artifact_subset_by_pin[pin].append(downloadable_artifact.artifact)

    archive_requirements = {
        req.project_name: req
        for req in root_requirements
        if req.url and isinstance(parse_requirement_string(str(req)), URLRequirement)
    }  # type: Dict[ProjectName, Requirement]

    dependants_by_project_name = defaultdict(
        OrderedSet
    )  # type: DefaultDict[ProjectName, OrderedSet[Tuple[ProjectName, Optional[Marker]]]]
    for locked_requirement in locked_resolve.locked_requirements:
        for dist in locked_requirement.requires_dists:
            marker = _elide_extras(dist.marker) if dist.marker else None  # type: Optional[Marker]
            dependants_by_project_name[dist.project_name].add(
                (locked_requirement.pin.project_name, marker)
            )

    packages = OrderedDict()  # type: OrderedDict[LockedRequirement, Dict[str, Any]]
    for locked_requirement in locked_resolve.locked_requirements:
        artifact_subset = artifact_subset_by_pin[locked_requirement.pin]
        if subset and not artifact_subset:
            continue

        package = OrderedDict()  # type: OrderedDict[str, Any]

        # https://peps.python.org/pep-0751/#packages-name
        # The name of the package normalized.
        package["name"] = locked_requirement.pin.project_name.normalized

        artifacts = artifact_subset or list(locked_requirement.iter_artifacts())
        if len(artifacts) != 1 or not isinstance(
            artifacts[0], (LocalProjectArtifact, UnFingerprintedLocalProjectArtifact)
        ):
            # https://peps.python.org/pep-0751/#packages-version
            # The version MUST NOT be included when it cannot be guaranteed to be consistent with
            # the code used (i.e. when a source tree is used).
            #
            # We do not include locked VCS requirements in the version elision since PEP-751
            # requires VCS locks have a commit-id and implies it's the commit id that must be used
            # to check out the project:
            # + https://peps.python.org/pep-0751/#packages-vcs-requested-revision
            # + https://peps.python.org/pep-0751/#packages-vcs-commit-id
            package["version"] = locked_requirement.pin.version.normalized

        # https://peps.python.org/pep-0751/#packages-marker
        marker = _calculate_marker(locked_requirement.pin.project_name, dependants_by_project_name)
        if marker:
            package["marker"] = str(marker)

        if locked_requirement.requires_python:
            # https://peps.python.org/pep-0751/#packages-requires-python
            package["requires-python"] = str(locked_requirement.requires_python)

        if include_dependency_info and locked_requirement.requires_dists:
            # https://peps.python.org/pep-0751/#packages-dependencies
            #
            # Since Pex only supports locking one version of any given project, the project name
            # is enough to disambiguate the dependency.
            dependencies = []  # type: List[Dict[str, Any]]
            for dep in locked_requirement.requires_dists:
                dependencies.append(InlineTable.create(("name", dep.project_name.normalized)))
            package["dependencies"] = sorted(
                # N.B.: Cast since MyPy can't track the setting of "name" in the dict just above.
                dependencies,
                key=lambda data: cast(str, data["name"]),
            )

        archive_requirement = archive_requirements.get(locked_requirement.pin.project_name)
        if archive_requirement:
            artifact_count = len(artifacts)
            production_assert(
                artifact_count == 1,
                "Expected a direct URL requirement to have exactly one artifact but "
                "{requirement} has {count}.",
                requirement=archive_requirement,
                count=artifact_count,
            )
            production_assert(
                isinstance(artifacts[0], FileArtifact),
                "Packages with an archive should resolve to FileArtifacts but resolved a "
                "{type} instead.",
                type=type(artifacts[0]),
            )
            archive_artifact = cast(FileArtifact, artifacts[0])

            archive = InlineTable()  # type: OrderedDict[str, Any]

            # https://peps.python.org/pep-0751/#packages-archive-url
            download_url = ArtifactURL.parse(archive_artifact.url.download_url)
            download_url_info = download_url.url_info._replace(
                fragment=download_url.fragment(excludes=("egg", "subdirectory"))
            )
            archive["url"] = urlparse.urlunparse(download_url_info)

            # https://peps.python.org/pep-0751/#packages-archive-hashes
            archive["hashes"] = InlineTable.create(
                (archive_artifact.fingerprint.algorithm, archive_artifact.fingerprint.hash)
            )

            # https://peps.python.org/pep-0751/#packages-archive-subdirectory
            subdirectory = archive_artifact.subdirectory
            if subdirectory:
                archive["subdirectory"] = subdirectory

            package["archive"] = archive
        else:
            wheels = []  # type: List[OrderedDict[str, Any]]
            for artifact in artifacts:
                if isinstance(artifact, FileArtifact):
                    file_artifact = InlineTable()  # type: OrderedDict[str, Any]

                    # https://peps.python.org/pep-0751/#packages-sdist-name
                    # https://peps.python.org/pep-0751/#packages-wheels-name
                    file_artifact["name"] = artifact.filename

                    # https://peps.python.org/pep-0751/#packages-sdist-url
                    # https://peps.python.org/pep-0751/#packages-wheels-url
                    file_artifact["url"] = artifact.url.download_url

                    # https://peps.python.org/pep-0751/#packages-sdist-hashes
                    # https://peps.python.org/pep-0751/#packages-wheels-hashes
                    file_artifact["hashes"] = InlineTable.create(
                        (artifact.fingerprint.algorithm, artifact.fingerprint.hash)
                    )
                    if artifact.is_source:
                        package["sdist"] = file_artifact
                    elif artifact.is_wheel:
                        wheels.append(file_artifact)
                    else:
                        # We dealt with direct URL archives above outside this loop; so this
                        # FileArtifact is unexpected.
                        production_assert(
                            False,
                            "Unexpected file artifact {filename} for locked requirement {pin}: "
                            "{url}".format(
                                filename=artifact.filename,
                                pin=locked_requirement.pin,
                                url=artifact.url.download_url,
                            ),
                        )
                elif isinstance(artifact, (UnFingerprintedVCSArtifact, VCSArtifact)):
                    if not artifact.commit_id:
                        raise ValueError(
                            "Cannot export {url} in a PEP-751 lock.\n"
                            "\n"
                            "A commit id is required to be resolved for VCS artifacts and none "
                            "was.\n"
                            "This most likely means the lock file was created by Pex older than "
                            "2.37.0, using an old `--pip-version` or that the lock was created "
                            "using Python 2.7.\n"
                            "You'll need to re-create the lock with a newer Pex or newer Python or "
                            "both to be able to export it in PEP-751 format.".format(
                                url=artifact.url.raw_url
                            )
                        )
                    vcs_artifact = InlineTable()  # type: OrderedDict[str, Any]

                    # https://peps.python.org/pep-0751/#packages-vcs-type
                    vcs_artifact["type"] = artifact.vcs.value

                    # https://peps.python.org/pep-0751/#packages-vcs-url
                    vcs_url, _ = VCSArtifact.split_requested_revision(artifact.url)
                    vcs_url_info = vcs_url.url_info._replace(
                        fragment=vcs_url.fragment(excludes=("egg", "subdirectory"))
                    )
                    if isinstance(artifact.url.scheme, VCSScheme):
                        vcs_scheme = artifact.url.scheme
                        # Strip the vcs part; e.g.: git+https -> https
                        vcs_url_info = vcs_url_info._replace(scheme=vcs_scheme.scheme)
                    vcs_artifact["url"] = urlparse.urlunparse(vcs_url_info)

                    # https://peps.python.org/pep-0751/#packages-vcs-requested-revision
                    if artifact.requested_revision:
                        vcs_artifact["requested-revision"] = artifact.requested_revision

                    # https://peps.python.org/pep-0751/#packages-vcs-commit-id
                    vcs_artifact["commit-id"] = artifact.commit_id

                    # https://peps.python.org/pep-0751/#packages-vcs-subdirectory
                    subdirectory = artifact.subdirectory
                    if subdirectory:
                        vcs_artifact["subdirectory"] = subdirectory

                    package["vcs"] = vcs_artifact
                else:
                    production_assert(
                        isinstance(
                            artifact, (LocalProjectArtifact, UnFingerprintedLocalProjectArtifact)
                        )
                    )
                    directory = InlineTable()  # type: OrderedDict[str, Any]

                    # https://peps.python.org/pep-0751/#packages-directory-path
                    directory["path"] = artifact.directory

                    # https://peps.python.org/pep-0751/#packages-directory-editable
                    directory["editable"] = artifact.editable

                    package["directory"] = directory

            if wheels:
                package["wheels"] = sorted(
                    # N.B.: Cast since MyPy can't track the setting of "name" in the dict above.
                    wheels,
                    key=lambda data: cast(str, data["name"]),
                    # N.B.: We reverse since it floats 3.9 and 3.13+ to the top with wheels for
                    # Pythons older than 3.13 descending below. Since 3.9 is the oldest officially
                    # supported CPython by Python as of this writing, this is generally the most
                    # useful sort.
                    reverse=True,
                )

        packages[locked_requirement] = package

    pylock["packages"] = list(packages.values())

    toml.dump(pylock, output)


if TYPE_CHECKING:
    _T = TypeVar("_T")


@attr.s(frozen=True)
class ParseContext(object):
    source = attr.ib()  # type: str
    _prefix = attr.ib(init=False)  # type: str
    table = attr.ib(factory=dict)  # type: Mapping[str, Any]
    path = attr.ib(default="")  # type: str

    def __attrs_post_init__(self):
        prefix = "Failed to parse the PEP-751 lock at {pylock}.".format(pylock=self.source)
        if self.path:
            prefix = "{prefix} Error parsing content at {path}.".format(
                prefix=prefix, path=self.path
            )
        object.__setattr__(self, "_prefix", prefix)

    def __bool__(self):
        # type: () -> bool
        return len(self.table) > 0

    # N.B.: For Python 2.7.
    __nonzero__ = __bool__

    def subpath(self, key):
        # type: (str) -> str
        return "{path}.{subpath}".format(path=self.path, subpath=key) if self.path else key

    def with_table(
        self,
        table,  # type: Mapping[str, Any]
        path=None,  # type: Optional[str]
    ):
        # type: (...) -> ParseContext
        production_assert(not self.path or path is not None)
        return ParseContext(
            source=self.source, table=table, path=self.subpath(path) if path else ""
        )

    def get_string(
        self,
        key,  # type: str
        default=None,  # type: Optional[str]
    ):
        # type: (...) -> str
        # The cast is of Python 2. The return type will actually be `unicode` in that case, but it
        # doesn't matter since there will be no further runtime type checks above this call.
        return cast(str, self.get(key, text, default=default))

    def get_array_of_strings(
        self,
        key,  # type: str
        default=None,  # type: Optional[List[str]]
    ):
        # type: (...) -> List[str]
        value = self.get(key, list, default=default)
        if not all(isinstance(item, text) for item in value):
            raise ResultError(
                self.error(
                    "Expected {key} to be an arrays of strings.".format(key=self.subpath(key))
                )
            )
        return cast("List[str]", value)

    def get_array_of_tables(
        self,
        key,  # type: str
        default=None,  # type: Optional[List[Dict[str, Any]]]
        diagnostic_key=None,  # type: Optional[str]
    ):
        # type: (...) -> List[ParseContext]
        value = self.get(key, list, default=default)
        if not all(
            isinstance(item, dict) and all(isinstance(key, text) for key in item) for item in value
        ):
            raise ResultError(
                self.error("Expected {key} to be an array of tables.".format(key=self.subpath(key)))
            )

        def diagnostic(data):
            # type: (Dict[str, Any]) -> str

            if not diagnostic_key:
                return ""

            diagnostic_value = data.get(diagnostic_key, None)
            if diagnostic_value is None:
                return ""

            value_repr = (
                '"{value}"'.format(value=diagnostic_value)
                if isinstance(diagnostic_value, text)
                else repr(diagnostic_value)
            )
            return "{{{key} = {value}}}".format(key=diagnostic_key, value=value_repr)

        return [
            self.with_table(
                item,
                path="{key}[{index}]{diagnostic}".format(
                    key=key, index=index, diagnostic=diagnostic(item)
                ),
            )
            for index, item in enumerate(value)
        ]

    def get_table(
        self,
        key,  # type: str
        default=None,  # type: Optional[Mapping[str, Any]]
    ):
        # type: (...) -> ParseContext
        value = self.get(key, dict, default=default)
        if not all(isinstance(name, text) for name in value):
            raise ResultError(
                self.error(
                    "Expected {key} to be a table but not all dict keys are strings.".format(
                        key=self.subpath(key)
                    )
                )
            )
        return self.with_table(value, path=key)

    def get(
        self,
        key,  # type: str
        item_type,  # type: Type[_T]
        default=None,  # type: Optional[_T]
    ):
        # type: (...) -> _T
        value = self.table.get(key, None)
        if value is None:
            if default is None:
                raise ResultError(
                    self.error("A value for {key} is required.".format(key=self.subpath(key)))
                )
            return default
        if not isinstance(value, item_type):
            raise ResultError(
                self.error(
                    "Expected {key} to be a {expected_type} but got a {value_type}.".format(
                        key=self.subpath(key), expected_type=item_type, value_type=type(value)
                    )
                )
            )
        return cast("_T", value)

    def error(
        self,
        msg,  # type: str
        err=None,  # type: Optional[Exception]
    ):
        # type: (...) -> Error
        return Error(
            os.linesep.join(
                (self._prefix, "{msg}: {err}".format(msg=msg, err=err) if err else msg)
            ),
        )


@attr.s(frozen=True)
class Dependency(object):
    index = attr.ib()  # type: int
    project_name = attr.ib()  # type: ProjectName


@attr.s(frozen=True)
class Package(object):
    index = attr.ib()  # type: int
    project_name = attr.ib()  # type: ProjectName
    artifact = (
        attr.ib()
    )  # type: Union[FileArtifact, UnFingerprintedLocalProjectArtifact, UnFingerprintedVCSArtifact]
    artifact_is_archive = attr.ib(default=False)  # type: bool
    version = attr.ib(default=None)  # type: Optional[Version]
    requires_python = attr.ib(default=None)  # type: Optional[SpecifierSet]
    marker = attr.ib(default=None)  # type: Optional[Marker]
    dependencies = attr.ib(default=None)  # type: Optional[Tuple[Dependency, ...]]
    additional_wheels = attr.ib(default=())  # type: Tuple[FileArtifact, ...]

    def as_dependency(self):
        # type: () -> Dependency
        return Dependency(index=self.index, project_name=self.project_name)

    @property
    def artifact_is_wheel(self):
        # type: () -> bool
        return isinstance(self.artifact, FileArtifact) and self.artifact.is_wheel

    @property
    def has_wheel(self):
        # type: () -> bool
        return self.artifact_is_wheel or len(self.additional_wheels) > 0

    def iter_wheels(self):
        # type: () -> Iterator[FileArtifact]
        if self.artifact_is_wheel:
            yield cast(FileArtifact, self.artifact)
        for wheel in self.additional_wheels:
            yield wheel

    def as_unparsed_requirement(self):
        # type: () -> str

        if isinstance(self.artifact, UnFingerprintedVCSArtifact):
            return self.artifact.as_unparsed_requirement(self.project_name)

        if self.artifact_is_archive or isinstance(
            self.artifact, UnFingerprintedLocalProjectArtifact
        ):
            return "{project_name} @ {url}".format(
                project_name=self.project_name, url=self.artifact.url.raw_url
            )

        if self.version:
            return "{project_name}{operator}{version}".format(
                project_name=self.project_name,
                operator="===" if self.version.is_legacy else "==",
                version=self.version,
            )

        return str(self.project_name)

    def as_requirement(self):
        # type: () -> Requirement
        return Requirement.parse(self.as_unparsed_requirement())

    def as_parsed_requirement(self):
        # type: () -> ParsedRequirement
        if isinstance(self.artifact, UnFingerprintedLocalProjectArtifact):
            path = (
                self.artifact.directory
                if os.path.isabs(self.artifact.directory)
                else "./{path}".format(path=self.artifact.directory)
            )
            return attr.evolve(
                (
                    parse_requirement_string("-e {path}".format(path=path))
                    if self.artifact.editable
                    else parse_requirement_string(path)
                ),
                project_name=self.project_name,
            )
        return parse_requirement_string(self.as_unparsed_requirement())

    def identify(self):
        # type: () -> str

        spec = (
            "{project_name} {version}".format(project_name=self.project_name, version=self.version)
            if self.version
            else str(self.project_name)
        )

        artifacts = ""  # type: str
        if isinstance(self.artifact, FileArtifact) and self.artifact.is_source:
            artifacts = "sdist"
        elif isinstance(self.artifact, UnFingerprintedLocalProjectArtifact):
            artifacts = "directory"
        elif isinstance(self.artifact, UnFingerprintedVCSArtifact):
            artifacts = "vcs checkout"
        elif self.artifact_is_wheel and not self.additional_wheels:
            artifacts = "wheel"

        if self.additional_wheels:
            if not artifacts:
                artifacts = "in {count} wheels".format(count=len(self.additional_wheels) + 1)
            else:
                artifacts = "{artifact} and {count}".format(
                    artifact=artifacts, count=len(self.additional_wheels)
                )

        return "{spec} {artifacts}".format(spec=spec, artifacts=artifacts)


@attr.s(frozen=True)
class IndexedPackage(object):
    index = attr.ib()  # type: int
    parse_context = attr.ib()  # type: ParseContext

    @property
    def package_data(self):
        # type: () -> Mapping[str, Any]
        return self.parse_context.table


@attr.s(frozen=True)
class PackageIndex(object):
    @classmethod
    def create(
        cls,
        packages_data,  # type: List[ParseContext]
    ):
        # type: (...) -> PackageIndex

        project_name_by_index = {}
        indexed_packages_by_name = defaultdict(
            list
        )  # type: DefaultDict[ProjectName, List[IndexedPackage]]
        for index, package_parse_context in enumerate(packages_data):
            project_name = ProjectName(package_parse_context.get_string("name"))
            project_name_by_index[index] = project_name
            indexed_packages_by_name[project_name].append(
                IndexedPackage(index, package_parse_context)
            )

        return cls(
            project_name_by_index=project_name_by_index,
            indexed_packages_by_name={
                project_name: tuple(packages)
                for project_name, packages in indexed_packages_by_name.items()
            },
        )

    _project_name_by_index = attr.ib()  # type: Mapping[int, ProjectName]
    _indexed_packages_by_name = attr.ib()  # type: Mapping[ProjectName, Tuple[IndexedPackage, ...]]

    def iter_packages(self):
        # type: () -> Iterator[IndexedPackage]
        for packages in self._indexed_packages_by_name.values():
            for package in packages:
                yield package

    def package_name(self, index):
        # type: (int) -> ProjectName
        return self._project_name_by_index[index]

    def packages(self, project_name):
        # type: (ProjectName) -> Optional[Tuple[IndexedPackage, ...]]
        return self._indexed_packages_by_name.get(project_name)


def spec_matches(
    spec,  # type: Any
    package_data,  # type: Any
):
    # type: (...) -> bool

    if isinstance(spec, dict) and isinstance(package_data, dict):
        for key, value in spec.items():
            if not spec_matches(value, package_data.get(key)):
                return False
        return True

    if isinstance(spec, list) and isinstance(package_data, list):
        # All instances of lists in packages are currently array of tables:
        # + dependencies
        # + wheels
        # + attestation-identities
        #
        # As such, we consider the list matches if any of its contained tables matches each of the
        # spec tables. This allows a dependency spec like so to match the torch cpu wheel in a lock
        # that also includes torch-2.7.0-cp311-none-macosx_11_0_arm64.whl (cuda 12.8):
        # {name = "torch", wheels = [{ name = "torch-2.7.0+xpu-cp39-cp39-win_amd64.whl" }]}
        for spec_item in spec:
            if not any(
                spec_matches(spec_item, package_data_item) for package_data_item in package_data
            ):
                return False
        return True

    # I have no clue why MyPy can't track this as bool.
    return cast(bool, spec == package_data)


@attr.s
class PackageParser(object):
    package_index = attr.ib()  # type: PackageIndex
    source = attr.ib()  # type: str

    parsed_packages_by_index = attr.ib(factory=dict)  # type: Dict[int, Package]

    @staticmethod
    def get_fingerprint(parse_context):
        # type: (ParseContext) -> Fingerprint

        hashes = parse_context.get_table("hashes")
        for algorithm in RANKED_ALGORITHMS:
            hash_value = hashes.get_string(algorithm, default="")
            if hash_value:
                return Fingerprint(algorithm=algorithm, hash=hash_value)

        raise ResultError(
            hashes.error("No hashes from `hashlib.algorithms_guaranteed` are present.")
        )

    def parse_url_or_path(self, parse_context):
        # type: (ParseContext) -> ArtifactURL

        url = parse_context.get_string("url", "")
        if not url:
            path = parse_context.get_string("path")
            if not os.path.isabs(path):
                path = os.path.join(os.path.dirname(self.source), path)
            url = "file://{path}".format(path=path)
        return ArtifactURL.parse(url)

    def parse(self, indexed_package):
        # type: (IndexedPackage) -> Union[Package, Error]

        index = indexed_package.index
        package = self.parsed_packages_by_index.get(index)
        if package:
            return package

        project_name = self.package_index.package_name(index)

        parse_context = indexed_package.parse_context
        raw_version = parse_context.get_string("version", default="")
        version = Version(raw_version) if raw_version else None

        raw_marker = parse_context.get_string("marker", default="")
        try:
            marker = Marker(raw_marker) if raw_marker else None
        except InvalidMarker as e:
            error_msg = str(e)
            if (
                sys.version_info[:2] < (3, 8)
                and ("dependency_groups" in raw_marker)
                or ("extras" in raw_marker)
            ):
                return parse_context.error(
                    "Failed to parse marker {raw_marker}: {error_msg}\n"
                    "It appears this marker uses `extras` or `dependency_groups` which are only "
                    "supported for Python 3.8 or newer.".format(
                        raw_marker=raw_marker, error_msg=error_msg
                    )
                )
            else:
                return parse_context.error(error_msg)

        raw_requires_python = parse_context.get_string("requires-python", default="")
        requires_python = SpecifierSet(raw_requires_python) if raw_requires_python else None

        dependencies = []  # type: List[Dependency]

        dep_parse_contexts = parse_context.get_array_of_tables(
            "dependencies", default=[], diagnostic_key="name"
        )
        for dep_idx, dep_parse_context in enumerate(dep_parse_contexts):
            dep_name = ProjectName(dep_parse_context.get_string("name"))

            package_deps = self.package_index.packages(dep_name)
            if not package_deps:
                return dep_parse_context.error(
                    "The {project_name} package depends on {dep_name}, but there is no {dep_name} "
                    "package in the packages array.".format(
                        project_name=project_name.raw, dep_name=dep_name.raw
                    )
                )

            deps = [
                indexed_package
                for indexed_package in package_deps
                if spec_matches(dep_parse_context.table, indexed_package.package_data)
            ]  # type: List[IndexedPackage]
            if not deps:
                return dep_parse_context.error(
                    "No matching {dep_name} package could be found for {project_name} "
                    "dependencies[{dep_idx}].".format(
                        dep_name=dep_name.raw, project_name=project_name.raw, dep_idx=dep_idx
                    )
                )
            elif len(deps) > 1:
                return dep_parse_context.error(
                    "More than one package matches {project_name} dependencies[{dep_idx}]:\n"
                    "{matches}".format(
                        project_name=project_name.raw,
                        dep_idx=dep_idx,
                        matches="\n".join(
                            "+ packages[{index}]".format(index=dep.index) for dep in deps
                        ),
                    )
                )
            dependencies.append(Dependency(index=deps[0].index, project_name=dep_name))

        vcs_parse_context = parse_context.get_table("vcs", default={})
        directory_parse_context = parse_context.get_table("directory", default={})
        archive_parse_context = parse_context.get_table("archive", default={})
        sdist_parse_context = parse_context.get_table("sdist", default={})
        wheels = parse_context.get_array_of_tables("wheels", default=[])

        def check_mutually_exclusive(
            key,  # type: str
            others,  # type: Iterable[Union[ParseContext, List[ParseContext]]]
        ):
            # type: (...) -> None
            other_artifacts = [other for other in others if other]
            if not other_artifacts:
                return
            raise ResultError(
                parse_context.error(
                    "{lead} mutually exclusive with {key}:\n"
                    "{other_artifacts}".format(
                        lead="This artifact is"
                        if len(other_artifacts) == 1
                        else "These artifacts are",
                        key=key,
                        other_artifacts="\n".join(
                            "+ {path}".format(
                                path=(
                                    other_artifact.path
                                    if isinstance(other_artifact, ParseContext)
                                    else parse_context.subpath("wheels")
                                )
                            )
                            for other_artifact in other_artifacts
                        ),
                    )
                )
            )

        artifact = (
            None
        )  # type: Optional[Union[FileArtifact, UnFingerprintedLocalProjectArtifact, UnFingerprintedVCSArtifact]]
        additional_wheels = []  # type: List[FileArtifact]
        if vcs_parse_context:
            check_mutually_exclusive(
                key=vcs_parse_context.path,
                others=(
                    directory_parse_context,
                    archive_parse_context,
                    sdist_parse_context,
                    wheels,
                ),
            )

            url = self.parse_url_or_path(vcs_parse_context)

            try:
                vcs_type = VCS.for_value(vcs_parse_context.get_string("type"))
            except ValueError as e:
                return vcs_parse_context.error("Invalid vcs `type`.", err=e)

            commit_id = vcs_parse_context.get_string("commit-id")

            requested_revision = (
                vcs_parse_context.get_string("requested-revision", default="") or None
            )

            subdirectory = vcs_parse_context.get_string("subdirectory", default="") or None
            if subdirectory:
                vcs_fragment_parameters = defaultdict(list)  # type: DefaultDict[str, List[str]]
                vcs_fragment_parameters.update(
                    (name, list(values)) for name, values in url.fragment_parameters.items()
                )
                vcs_fragment_parameters["subdirectory"].append(subdirectory)
                url = ArtifactURL.parse(
                    url.url_info._replace(
                        fragment=ArtifactURL.create_fragment(vcs_fragment_parameters)
                    ).geturl()
                )

            artifact = UnFingerprintedVCSArtifact(
                url,
                verified=True,
                vcs=vcs_type,
                requested_revision=requested_revision,
                commit_id=commit_id,
            )
        elif directory_parse_context:
            check_mutually_exclusive(
                key=directory_parse_context.path,
                others=(vcs_parse_context, archive_parse_context, sdist_parse_context, wheels),
            )

            path = directory_parse_context.get_string("path")
            if not os.path.isabs(path):
                path = os.path.normpath(os.path.join(os.path.dirname(self.source), path))
            subdirectory = directory_parse_context.get_string("subdirectory", default="") or None
            if subdirectory:
                path = os.path.normpath(os.path.join(path, subdirectory))
            url = ArtifactURL.parse("file://{path}".format(path=path))

            editable = directory_parse_context.get("editable", bool, default=False)

            artifact = UnFingerprintedLocalProjectArtifact(
                url, verified=True, directory=path, editable=editable
            )
        elif archive_parse_context:
            url = self.parse_url_or_path(archive_parse_context)
            subdirectory = archive_parse_context.get_string("subdirectory", default="") or None
            if subdirectory:
                archive_fragment_parameters = defaultdict(list)  # type: DefaultDict[str, List[str]]
                archive_fragment_parameters.update(
                    (name, list(values)) for name, values in url.fragment_parameters.items()
                )
                archive_fragment_parameters["subdirectory"].append(subdirectory)
                url = ArtifactURL.parse(
                    url.url_info._replace(
                        fragment=ArtifactURL.create_fragment(archive_fragment_parameters)
                    ).geturl()
                )

            fingerprint = self.get_fingerprint(archive_parse_context)
            filename = os.path.basename(url.path)

            artifact = FileArtifact(url, verified=False, fingerprint=fingerprint, filename=filename)
        else:
            check_mutually_exclusive(
                key="{sdist} and {wheels}".format(
                    sdist=parse_context.subpath("sdist"), wheels=parse_context.subpath("wheels")
                ),
                others=(vcs_parse_context, directory_parse_context, archive_parse_context),
            )

            if sdist_parse_context:
                url = self.parse_url_or_path(sdist_parse_context)
                fingerprint = self.get_fingerprint(sdist_parse_context)

                # N.B.: We used to use `name` when present, but it appears at least `uv` writes down
                # the normalized wheel name here even when the basename of the index URL for the
                # file is non-normalized. This leads to issues collecting the files after Pip
                # downloads them using the index URL.
                # See: https://github.com/pex-tool/pex/issues/2772
                filename = os.path.basename(url.path)

                artifact = FileArtifact(
                    url, verified=False, fingerprint=fingerprint, filename=filename
                )
            if wheels:
                for whl_idx, whl_parse_context in enumerate(wheels):
                    url = self.parse_url_or_path(whl_parse_context)
                    fingerprint = self.get_fingerprint(whl_parse_context)

                    # N.B.: We used to use `name` when present, but it appears at least `uv` writes down
                    # the normalized wheel name here even when the basename of the index URL for the
                    # file is non-normalized. This leads to issues collecting the files after Pip
                    # downloads them using the index URL.
                    # See: https://github.com/pex-tool/pex/issues/2772
                    filename = os.path.basename(url.path)

                    wheel_artifact = FileArtifact(
                        url, verified=False, fingerprint=fingerprint, filename=filename
                    )
                    if artifact:
                        additional_wheels.append(wheel_artifact)
                    else:
                        artifact = wheel_artifact

        if artifact is None:
            return parse_context.error("Package must define an artifact.")

        package = Package(
            index=index,
            project_name=project_name,
            artifact=artifact,
            artifact_is_archive=bool(archive_parse_context),
            version=version,
            requires_python=requires_python,
            marker=marker,
            dependencies=tuple(dependencies) if dependencies is not None else None,
            additional_wheels=tuple(additional_wheels),
        )
        self.parsed_packages_by_index[index] = package
        return package


class ResolveError(Exception):
    pass


@attr.s(frozen=True)
class PackageEvaluator(object):
    @classmethod
    def create(
        cls,
        source,  # type: str
        target,  # type: Target
        extras=frozenset(),  # type: FrozenSet[str]
        dependency_groups=frozenset(),  # type: FrozenSet[str]
        constraints=(),  # type: Iterable[Requirement]
        build_configuration=BuildConfiguration(),  # type: BuildConfiguration
        dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
    ):
        # type: (...) -> PackageEvaluator

        constraints_by_project_name = {
            constraint.project_name: constraint.as_constraint() for constraint in constraints
        }

        if (extras or dependency_groups) and sys.version_info[:2] < (3, 8):
            suggestion = ""
            if target.python_version and target.python_version >= (3, 8):
                suggestion = (
                    "\n"
                    "The target Python is version {version}; so you should be able to re-run Pex "
                    "using a newer Python as a work-around.".format(
                        version=target.python_version_str
                    )
                )
            raise ResolveError(
                "Pex can only resolve extras and dependency-groups from {source} using Python 3.8 "
                "or newer.{suggestion}".format(source=source, suggestion=suggestion)
            )

        # The dict from MarkerEnvironment.as_dict is typed Dict[str, str], which is true. We'll
        # add the frozenset values though below, transforming the type.
        marker_environment = cast(
            "Dict[str, Union[str, FrozenSet[str]]]", target.marker_environment.as_dict()
        )
        if sys.version_info[:2] >= (3, 8):
            marker_environment["extras"] = extras
            marker_environment["dependency_groups"] = dependency_groups

        return cls(
            source=source,
            target=target,
            marker_environment=marker_environment,
            constraints_by_project_name=constraints_by_project_name,
            build_configuration=build_configuration,
            dependency_configuration=dependency_configuration,
        )

    source = attr.ib()  # type: str
    target = attr.ib()  # type: Target
    marker_environment = attr.ib()  # type: Mapping[str, Union[str, FrozenSet[str]]]
    constraints_by_project_name = attr.ib(factory=dict)  # type: Mapping[ProjectName, Constraint]
    build_configuration = attr.ib(default=BuildConfiguration())  # type: BuildConfiguration
    dependency_configuration = attr.ib(
        default=DependencyConfiguration()
    )  # type: DependencyConfiguration

    def _excluded(self, package):
        # type: (Package) -> bool
        return len(self.dependency_configuration.excluded_by(package.as_requirement())) > 0

    def _satisfies_build_configuration(self, package):
        # type: (Package) -> bool

        if package.has_wheel and self.build_configuration.allow_wheel(package.project_name):
            return True
        return self.build_configuration.allow_build(package.project_name)

    def _satisfies_constraints(
        self,
        project_name,  # type: ProjectName
        version=None,  # type: Optional[Version]
    ):
        # type: (...) -> bool

        if not version:
            return True

        constraint = self.constraints_by_project_name.get(project_name)
        if not constraint:
            return True

        return constraint.contains(version)

    def applies(self, package):
        # type: (Package) -> bool

        if self._excluded(package):
            return False

        if not self._satisfies_build_configuration(package):
            return False

        if not self._satisfies_constraints(package.project_name, package.version):
            return False

        if package.requires_python and not self.target.requires_python_applies(
            package.requires_python, source=package.identify()
        ):
            return False

        if package.marker and not package.marker.evaluate(self.marker_environment):
            return False

        return True

    def select_best_fit_wheel(self, wheels):
        # type: (Sequence[FileArtifact]) -> Optional[FileArtifact]

        production_assert(len(wheels) > 0)

        best_match = None  # type: Optional[RankedTag]
        selected_wheel = None  # type: Optional[FileArtifact]
        for wheel in wheels:
            wheel_tags = CompatibilityTags.from_wheel(wheel.filename)
            ranked_tag = self.target.supported_tags.best_match(wheel_tags)
            if ranked_tag and (
                not best_match or ranked_tag == ranked_tag.select_higher_rank(best_match)
            ):
                best_match = ranked_tag
                selected_wheel = wheel
        return selected_wheel

    def select_best_fit_artifact(self, package):
        # type: (Package) -> Union[FileArtifact, UnFingerprintedLocalProjectArtifact, UnFingerprintedVCSArtifact]

        if not package.has_wheel or not self.build_configuration.allow_wheel(package.project_name):
            # A source distribution (sdist, directory, archive or vcs).
            return package.artifact

        if not package.additional_wheels:
            # A sole wheel.
            return package.artifact

        best_fit_wheel = self.select_best_fit_wheel(list(package.iter_wheels()))
        if best_fit_wheel:
            return best_fit_wheel
        if package.artifact.is_source:
            return package.artifact

        raise ResolveError(
            "No locked artifacts for {package} in {source} are compatible with {target}.".format(
                package=package.identify(),
                source=self.source,
                target=self.target.render_description(),
            )
        )


@attr.s(frozen=True)
class ResolvedPackages(object):
    packages = attr.ib()  # type: Tuple[Package, ...]
    resolved = attr.ib()  # type: Resolved[Pylock]

    def resolve_roots(self):
        # type: () -> Iterable[Package]

        dependants_by_package_index = defaultdict(list)  # type: DefaultDict[int, List[Package]]
        for package in self.packages:
            if package.dependencies:
                for dependency in package.dependencies:
                    dependants_by_package_index[dependency.index].append(package)

        return tuple(
            package for package in self.packages if not dependants_by_package_index[package.index]
        )


@attr.s(frozen=True)
class Pylock(object):
    @classmethod
    def parse(cls, pylock_toml_path):
        # type: (str) -> Union[Pylock, Error]

        parse_context = ParseContext(source=pylock_toml_path)
        try:
            parse_context = parse_context.with_table(toml.load(pylock_toml_path))
        except TomlDecodeError as e:
            return parse_context.error("Failed to parse TOML", e)

        lock_version = Version(
            parse_context.get_string(
                "lock-version",
                "Pex only supports lock version 1.0 and refuses to guess compatibility.",
            )
        )
        if lock_version != Version("1.0"):
            return parse_context.error(
                "Found `lock-version` {version}, but Pex only supports version 1.0.".format(
                    version=lock_version.raw
                )
            )

        environments = tuple(
            map(Marker, parse_context.get_array_of_strings("environments", default=[]))
        )
        requires_python = SpecifierSet(parse_context.get_string("requires-python", default=""))
        extras = frozenset(parse_context.get_array_of_strings("extras", default=[]))
        dependency_groups = frozenset(
            parse_context.get_array_of_strings("dependency-groups", default=[])
        )
        default_groups = frozenset(parse_context.get_array_of_strings("default-groups", default=[]))
        created_by = parse_context.get_string("created-by")

        packages_data = parse_context.get_array_of_tables(
            "packages", default=[], diagnostic_key="name"
        )
        package_index = PackageIndex.create(packages_data)
        package_parser = PackageParser(package_index=package_index, source=pylock_toml_path)

        local_project_requirement_mapping = {}  # type: Dict[str, Requirement]
        packages = []  # type: List[Package]
        for indexed_package in package_index.iter_packages():
            package = try_(package_parser.parse(indexed_package))
            if isinstance(package.artifact, UnFingerprintedLocalProjectArtifact):
                directory = package.artifact.directory
                if not os.path.isabs(directory):
                    directory = os.path.normpath(
                        os.path.join(os.path.dirname(pylock_toml_path), directory)
                    )
                local_project_requirement_mapping[directory] = Requirement.parse(
                    "{project_name} @ file://{directory}".format(
                        project_name=package.project_name, directory=directory
                    )
                )
            packages.append(package)

        return cls(
            lock_version=lock_version,
            created_by=created_by,
            packages=tuple(packages),
            local_project_requirement_mapping=local_project_requirement_mapping,
            source=pylock_toml_path,
            environments=environments,
            requires_python=requires_python,
            extras=extras,
            dependency_groups=dependency_groups,
            default_groups=default_groups,
        )

    lock_version = attr.ib()  # type: Version
    created_by = attr.ib()  # type: str
    packages = attr.ib()  # type: Tuple[Package, ...]

    local_project_requirement_mapping = attr.ib()  # type: Mapping[str, Requirement]
    source = attr.ib()  # type: str

    environments = attr.ib(default=())  # type: Tuple[Marker, ...]
    requires_python = attr.ib(default=SpecifierSet())  # type: SpecifierSet
    extras = attr.ib(default=())  # type: FrozenSet[str]
    dependency_groups = attr.ib(default=())  # type: FrozenSet[str]
    default_groups = attr.ib(default=())  # type: FrozenSet[str]

    def resolve(
        self,
        target,  # type: Target
        requirements,  # type: Iterable[Requirement]
        extras=frozenset(),  # type: FrozenSet[str]
        dependency_groups=frozenset(),  # type: FrozenSet[str]
        constraints=(),  # type: Iterable[Requirement]
        transitive=True,  # type: bool
        build_configuration=BuildConfiguration(),  # type: BuildConfiguration
        dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
    ):
        # type: (...) -> Union[ResolvedPackages, Error]

        if not target.requires_python_applies(self.requires_python, source=self.source):
            return Error(
                "This lock only supports Python {specifier}.".format(specifier=self.requires_python)
            )

        def format_sequence(sequence):
            # type: (Sequence[str]) -> str
            head = ", ".join(sequence[:-1])
            tail = sequence[-1]
            return "{head} and {tail}".format(head=head, tail=tail) if head else tail

        missing_extras = sorted(extras - self.extras)
        if missing_extras:
            missing_extras_error_lines = []  # type: List[str]
            if len(extras) == 1:
                missing_extras_error_lines.append(
                    "The extra {extra} was requested but it is not available in {source}.".format(
                        extra=missing_extras[0], source=self.source
                    )
                )
            else:
                missing_extras_error_lines.append(
                    "The extras {extras} were requested but not all are available in "
                    "{source}.".format(extras=format_sequence(missing_extras), source=self.source)
                )
            missing_extras_error_lines.append(
                "The available {extra} {are}:\n+ {extras}".format(
                    extra=pluralize(self.extras, "extra"),
                    are="is" if len(self.extras) == 1 else "are",
                    extras=format_sequence(sorted(self.extras)),
                )
            )
            return Error("\n".join(missing_extras_error_lines))

        groups = self.default_groups
        if dependency_groups:
            missing_groups = sorted(dependency_groups - self.dependency_groups)
            if missing_groups:
                missing_groups_error_lines = []  # type: List[str]
                if len(dependency_groups) == 1:
                    missing_groups_error_lines.append(
                        "The dependency group {group} was requested but it is not available in "
                        "{source}.".format(group=missing_groups[0], source=self.source)
                    )
                else:
                    missing_groups_error_lines.append(
                        "The dependency groups {groups} were requested but not all are available "
                        "in {source}.".format(
                            groups=format_sequence(missing_groups), source=self.source
                        )
                    )
                missing_groups_error_lines.append(
                    "The available dependency {group} {are} {groups}".format(
                        group=pluralize(self.extras, "group"),
                        are="is" if len(self.extras) == 1 else "are",
                        groups=format_sequence(sorted(self.dependency_groups)),
                    )
                )
                return Error("\n".join(missing_groups_error_lines))
            groups = dependency_groups

        package_evaluator = PackageEvaluator.create(
            source=self.source,
            target=target,
            extras=extras,
            dependency_groups=groups,
            constraints=constraints,
            build_configuration=build_configuration,
            dependency_configuration=dependency_configuration,
        )
        applicable_packages = [
            package for package in self.packages if package_evaluator.applies(package)
        ]

        packages_by_project_name = defaultdict(
            list
        )  # type: DefaultDict[ProjectName, List[Package]]
        for package in applicable_packages:
            packages_by_project_name[package.project_name].append(package)

        if requirements:
            required_project_names = deque(
                OrderedSet(requirement.project_name for requirement in requirements)
            )
            visited_projects = set()  # type: Set[ProjectName]
            packages = OrderedSet()  # type: OrderedSet[Package]
            while required_project_names:
                project_name = required_project_names.popleft()
                if project_name in visited_projects:
                    continue
                visited_projects.add(project_name)
                selected_packages = packages_by_project_name[project_name]
                if transitive:
                    for selected_package in selected_packages:
                        if selected_package.dependencies:
                            for dep in selected_package.dependencies:
                                required_project_names.append(dep.project_name)
                packages.update(selected_packages)

            applicable_packages = list(packages)
            for project_name in list(packages_by_project_name):
                if project_name not in visited_projects:
                    packages_by_project_name.pop(project_name)

        ambiguous_packages = {
            project_name: packages
            for project_name, packages in packages_by_project_name.items()
            if len(packages) > 1
        }
        if ambiguous_packages:
            return Error(
                "Found more than one match for the following projects in {source}.\n"
                "{ambiguous_packages}\n"
                "Pex resolves must produce a unique package per project.".format(
                    ambiguous_packages="\n".join(
                        "+ {project_name}:\n"
                        "  {packages}".format(
                            project_name=project_name,
                            packages="\n  ".join(package.identify() for package in packages),
                        )
                        for project_name, packages in ambiguous_packages.items()
                    ),
                    source=self.source,
                )
            )

        requirements_by_project_name = defaultdict(
            list
        )  # type: DefaultDict[ProjectName, List[Requirement]]
        if requirements:
            for requirement in requirements:
                requirements_by_project_name[requirement.project_name].append(requirement)
        else:
            for package in applicable_packages:
                requirements_by_project_name[package.project_name].append(package.as_requirement())

        downloadable_artifacts = []  # type: List[DownloadableArtifact]
        for package in applicable_packages:
            artifact = package_evaluator.select_best_fit_artifact(package)
            satisfied_direct_requirements = requirements_by_project_name[package.project_name]
            downloadable_artifacts.append(
                DownloadableArtifact(
                    project_name=package.project_name,
                    version=package.version,
                    artifact=artifact,
                    satisfied_direct_requirements=SortedTuple(
                        satisfied_direct_requirements, key=str
                    ),
                )
            )

        return ResolvedPackages(
            packages=tuple(applicable_packages),
            resolved=Resolved[Pylock](
                target_specificity=1.0, downloadable_artifacts=downloadable_artifacts, source=self
            ),
        )

    def render_description(self):
        # type: () -> str
        return "{source} created by {created_by}".format(
            source=self.source, created_by=self.created_by
        )


@attr.s(frozen=True)
class PylockSubsetResult(object):
    subset_result = attr.ib()  # type: SubsetResult[Pylock]
    packages_by_target = attr.ib()  # type: Mapping[Target, Tuple[Package, ...]]


def subset(
    targets,  # type: Targets
    pylock,  # type: Pylock
    requirement_configuration=RequirementConfiguration(),  # type: RequirementConfiguration
    extras=frozenset(),  # type: FrozenSet[str]
    dependency_groups=frozenset(),  # type: FrozenSet[str]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    build_configuration=BuildConfiguration(),  # type: BuildConfiguration
    transitive=True,  # type: bool
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> Union[PylockSubsetResult, Error]

    parsed_requirements = tuple(requirement_configuration.parse_requirements(network_configuration))
    constraints = tuple(
        parsed_constraint.requirement
        for parsed_constraint in requirement_configuration.parse_constraints(network_configuration)
    )
    missing_local_projects = []  # type: List[Text]
    requirements_to_resolve = OrderedSet()  # type: OrderedSet[Requirement]
    for parsed_requirement in parsed_requirements:
        if isinstance(parsed_requirement, LocalProjectRequirement):
            local_project_requirement = pylock.local_project_requirement_mapping.get(
                os.path.abspath(parsed_requirement.path)
            )
            if local_project_requirement:
                requirements_to_resolve.add(
                    attr.evolve(local_project_requirement, editable=parsed_requirement.editable)
                )
            else:
                missing_local_projects.append(parsed_requirement.line.processed_text)
        else:
            requirements_to_resolve.add(parsed_requirement.requirement)
    if missing_local_projects:
        return Error(
            "Found {count} local project {requirements} not present in the lock at {lock}:\n"
            "{missing}\n"
            "\n"
            "Perhaps{for_example} you meant to use `--project {project}`?".format(
                count=len(missing_local_projects),
                requirements=pluralize(missing_local_projects, "requirement"),
                lock=pylock.render_description(),
                missing="\n".join(
                    "{index}. {missing}".format(index=index, missing=missing)
                    for index, missing in enumerate(missing_local_projects, start=1)
                ),
                for_example=", as one example," if len(missing_local_projects) > 1 else "",
                project=missing_local_projects[0],
            )
        )

    resolved_packages_by_target = OrderedDict()  # type: OrderedDict[Target, ResolvedPackages]
    errors_by_target = {}  # type: Dict[Target, Error]
    with TRACER.timed(
        "Resolving urls to fetch for {count} requirements from lock {lockfile}".format(
            count=len(parsed_requirements), lockfile=pylock.render_description()
        )
    ):
        for target in targets.unique_targets():
            if pylock.environments and not any(
                marker.evaluate(target.marker_environment.as_dict())
                for marker in pylock.environments
            ):
                errors_by_target[target] = Error(
                    "This lock only works in limited environments, none of which support the "
                    "current target.\n"
                    "The supported environments are:\n"
                    "{environments}".format(
                        environments="\n".join(
                            "+ {env}".format(env=env) for env in pylock.environments
                        ),
                    )
                )
                continue

            resolved_packages = pylock.resolve(
                target,
                requirements_to_resolve,
                extras=extras,
                dependency_groups=dependency_groups,
                constraints=constraints,
                build_configuration=build_configuration,
                transitive=transitive,
                dependency_configuration=dependency_configuration,
            )
            if isinstance(resolved_packages, ResolvedPackages):
                resolved_packages_by_target[target] = resolved_packages
            else:
                errors_by_target[target] = resolved_packages

    if errors_by_target:
        return Error(
            "Failed to resolve compatible artifacts from {lock} for {count} {targets}:\n"
            "{errors}".format(
                lock="lock {source}".format(source=pylock.render_description()),
                count=len(errors_by_target),
                targets=pluralize(errors_by_target, "target"),
                errors="\n".join(
                    "{index}. {target}: {error}".format(index=index, target=target, error=error)
                    for index, (target, error) in enumerate(errors_by_target.items(), start=1)
                ),
            )
        )

    parsed_requirements = parsed_requirements or tuple(
        OrderedSet(
            package.as_parsed_requirement()
            for resolved_packages in resolved_packages_by_target.values()
            for package in resolved_packages.resolve_roots()
        )
    )

    return PylockSubsetResult(
        subset_result=SubsetResult[Pylock](
            requirements=parsed_requirements,
            subsets=tuple(
                Subset[Pylock](target=target, resolved=resolved_packages.resolved)
                for target, resolved_packages in resolved_packages_by_target.items()
            ),
        ),
        packages_by_target={
            target: resolved_packages.packages
            for target, resolved_packages in resolved_packages_by_target.items()
        },
    )
