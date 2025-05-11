# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from collections import OrderedDict, defaultdict

from pex import toml
from pex.dist_metadata import Requirement
from pex.exceptions import production_assert
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.requirements import URLRequirement, parse_requirement_string
from pex.resolve.locked_resolve import (
    DownloadableArtifact,
    FileArtifact,
    LocalProjectArtifact,
    LockedRequirement,
    LockedResolve,
    TargetSystem,
    VCSArtifact,
)
from pex.resolve.lockfile.requires_dist import remove_unused_requires_dist
from pex.resolve.resolved_requirement import Pin
from pex.third_party.packaging.markers import Marker
from pex.toml import InlineTable
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import IO, Any, DefaultDict, Dict, Iterable, List, Mapping, Optional, Tuple, Union


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
        return "platform_system = 'Linux'"
    elif system is TargetSystem.MAC:
        return "platform_system = 'Darwin'"
    else:
        production_assert(system is TargetSystem.WINDOWS)
        return "platform_system = 'Windows'"


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
    )  # type: DefaultDict[Pin, List[Union[FileArtifact, LocalProjectArtifact, VCSArtifact]]]
    for downloadable_artifact in subset:
        artifact_subset_by_pin[downloadable_artifact.pin].append(downloadable_artifact.artifact)

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
        if len(artifacts) != 1 or not isinstance(artifacts[0], LocalProjectArtifact):
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
                "{requirement} has {count}.".format(
                    requirement=archive_requirement, count=artifact_count
                ),
            )
            artifact = artifacts[0]
            archive = InlineTable()  # type: OrderedDict[str, Any]

            # https://peps.python.org/pep-0751/#packages-archive-url
            archive["url"] = artifact.url.download_url

            # https://peps.python.org/pep-0751/#packages-archive-hashes
            archive["hashes"] = InlineTable.create(
                (artifact.fingerprint.algorithm, artifact.fingerprint.hash)
            )

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
                elif isinstance(artifact, VCSArtifact):
                    if not artifact.commit_id:
                        raise ValueError(
                            "Cannot export {url} in a PEP-751 lock.\n"
                            "\n"
                            "A commit id is required to be resolved for VCS artifacts and none "
                            "was.\n"
                            "This most likely means the lock file was created by Pex older than "
                            "2.37.0 or that the lock was created using Python 2.7.\n"
                            "You'll need to re-create the lock with a newer Pex or newer Python or "
                            "both to be able to export it in PEP-751 format.".format(
                                url=artifact.url.raw_url
                            )
                        )
                    vcs_artifact = InlineTable()  # type: OrderedDict[str, Any]

                    # https://peps.python.org/pep-0751/#packages-vcs-type
                    vcs_artifact["type"] = artifact.vcs.value

                    # https://peps.python.org/pep-0751/#packages-vcs-url
                    vcs_artifact["url"] = artifact.vcs_url

                    # https://peps.python.org/pep-0751/#packages-vcs-requested-revision
                    if artifact.requested_revision:
                        vcs_artifact["requested-revision"] = artifact.requested_revision

                    # https://peps.python.org/pep-0751/#packages-vcs-commit-id
                    vcs_artifact["commit-id"] = artifact.commit_id

                    # https://peps.python.org/pep-0751/#packages-vcs-subdirectory
                    if artifact.subdirectory:
                        vcs_artifact["subdirectory"] = artifact.subdirectory

                    package["vcs"] = vcs_artifact
                else:
                    production_assert(isinstance(artifact, LocalProjectArtifact))
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
