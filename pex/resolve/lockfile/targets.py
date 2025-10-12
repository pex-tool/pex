from __future__ import absolute_import

import itertools
import os.path
import tempfile
from collections import OrderedDict, defaultdict

from pex import atexit
from pex.common import pluralize, safe_delete
from pex.interpreter_constraints import iter_compatible_versions
from pex.interpreter_implementation import InterpreterImplementation
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.resolve.package_repository import ReposConfiguration
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.target_system import (
    ExtraMarkers,
    MarkerEnv,
    TargetSystem,
    UniversalTarget,
    has_marker,
)
from pex.resolver import DownloadRequest
from pex.targets import LocalInterpreter, Targets
from pex.third_party.packaging.markers import Marker
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import (
        DefaultDict,
        Dict,
        FrozenSet,
        Iterable,
        Iterator,
        List,
        Mapping,
        Optional,
        Text,
        Tuple,
    )

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def _calculate_split_markers(
    requirement_configuration,  # type: RequirementConfiguration
    network_configuration,  # type: NetworkConfiguration
    repos_configuration,  # type: ReposConfiguration
):
    # type: (...) -> Mapping[str, Marker]

    split_markers = {
        str(scope.marker): scope.marker
        for repo in itertools.chain(
            repos_configuration.index_repos, repos_configuration.find_links_repos
        )
        for scope in repo.scopes
        if scope.marker
    }

    projects_with_markers = defaultdict(dict)  # type: DefaultDict[ProjectName, Dict[str, Marker]]
    for requirement in requirement_configuration.parse_requirements(network_configuration):
        if requirement.project_name and requirement.marker:
            projects_with_markers[requirement.project_name][
                str(requirement.marker)
            ] = requirement.marker
    for constraint in requirement_configuration.parse_constraints(network_configuration):
        if constraint.marker:
            projects_with_markers[constraint.project_name][
                str(constraint.marker)
            ] = constraint.marker
    split_markers.update(
        (marker_str, marker)
        for markers in projects_with_markers.values()
        for marker_str, marker in markers.items()
        # N.B.: We only split the universal resolve for root requirements that have two or
        # more marker variants. If there is just one, that represents a conditional
        # dependency which can be included in a single resolve without splitting.
        if len(markers) > 1
    )

    return split_markers


def _iter_universal_targets(
    universal_target,  # type: UniversalTarget
    split_markers,  # type: Mapping[str, Marker]
):
    # type: (...) -> Iterator[UniversalTarget]

    target_systems = universal_target.systems or TargetSystem.values()

    interpreter_implementations = (
        (universal_target.implementation,)
        if universal_target.implementation
        else InterpreterImplementation.values()
    )

    requires_pythons = OrderedSet()  # type: OrderedSet[SpecifierSet]
    has_python_version = any(
        has_marker(marker, "python_version") for marker in split_markers.values()
    )
    has_python_full_version = any(
        has_marker(marker, "python_full_version") for marker in split_markers.values()
    )
    if has_python_full_version:
        requires_pythons.update(
            SpecifierSet(
                "=={major}.{minor}.{patch}".format(
                    major=version[0], minor=version[1], patch=version[2]
                )
            )
            for version in iter_compatible_versions(universal_target.requires_python)
        )
    elif has_python_version:
        requires_pythons.update(
            SpecifierSet("=={major}.{minor}.*".format(major=version[0], minor=version[1]))
            for version in OrderedSet(
                version[:2]
                for version in iter_compatible_versions(universal_target.requires_python)
            )
        )
    else:
        requires_pythons.update(universal_target.requires_python)
    if not requires_pythons:
        requires_pythons.add(SpecifierSet())

    systems_by_markers = defaultdict(
        list
    )  # type: DefaultDict[FrozenSet[str], List[Tuple[TargetSystem.Value, InterpreterImplementation.Value, SpecifierSet]]]
    for system in target_systems:
        for implementation in interpreter_implementations:
            for python_specifier in requires_pythons:
                marker_env = MarkerEnv.create(
                    extras=(),
                    universal_target=UniversalTarget(
                        implementation=implementation,
                        systems=(system,),
                        requires_python=(python_specifier,),
                    ),
                )
                system_repo_markers = frozenset(
                    marker_str
                    for marker_str, marker in split_markers.items()
                    if marker_env.evaluate(marker)
                )
                systems_by_markers[system_repo_markers].append(
                    (system, implementation, python_specifier)
                )

    for markers, value in systems_by_markers.items():
        systems = OrderedSet()  # type: OrderedSet[TargetSystem.Value]
        implementations = OrderedSet()  # type: OrderedSet[InterpreterImplementation.Value]
        requires_python = OrderedSet()  # type: OrderedSet[SpecifierSet]
        for system, implementation, python_specifier in value:
            systems.add(system)
            implementations.add(implementation)
            requires_python.add(python_specifier)
        impl = implementations.pop() if len(implementations) == 1 else None
        yield UniversalTarget(
            implementation=impl,
            systems=tuple(systems),
            requires_python=tuple(requires_python),
        )


if TYPE_CHECKING:
    from pex.requirements import ParsedRequirement


@attr.s(frozen=True)
class DownloadInput(object):
    download_requests = attr.ib()  # type: Tuple[DownloadRequest, ...]
    direct_requirements = attr.ib()  # type: Tuple[ParsedRequirement, ...]


def _comment_out_requirements(
    requirements_file,  # type: Text
    requirements,  # type: Iterable[ParsedRequirement]
):
    # type: (...) -> Text

    lines_to_comment_out = set(
        itertools.chain.from_iterable(
            range(requirement.line.start_line, requirement.line.end_line + 1)
            for requirement in requirements
        )
    )

    # N.B.: We create the edited requirements file in the same directory as the original so that any
    # relative path references in the requirements file are still valid.
    out_fd, edited_requirements_file = tempfile.mkstemp(
        dir=os.path.dirname(requirements_file),
        prefix="pex_lock_split.",
        suffix=".{file_name}".format(file_name=os.path.basename(requirements_file)),
    )
    atexit.register(safe_delete, edited_requirements_file)
    try:
        with open(requirements_file, "rb") as in_fp:
            for line_no, text in enumerate(in_fp, start=1):
                if line_no in lines_to_comment_out:
                    os.write(out_fd, b"# ")
                os.write(out_fd, text)
    finally:
        os.close(out_fd)
    return edited_requirements_file


@attr.s
class Split(object):
    requirements_by_project_name = attr.ib(
        factory=OrderedDict
    )  # type: OrderedDict[ProjectName, ParsedRequirement]
    provenance = attr.ib(factory=OrderedSet)  # type: OrderedSet[ParsedRequirement]

    def applies(
        self,
        universal_target,  # type: UniversalTarget
        requirement,  # type: ParsedRequirement
    ):
        # type: (...) -> bool

        if not requirement.marker:
            return True

        requirements = [(req.marker, str(req)) for req in self.provenance if req.marker]
        if not requirements:
            return True

        marker_env = attr.evolve(
            universal_target, extra_markers=ExtraMarkers.extract(requirements)
        ).marker_env()
        return marker_env.evaluate(requirement.marker)

    def add(
        self,
        universal_target,  # type: UniversalTarget
        project_name,  # type: ProjectName
        requirement,  # type: ParsedRequirement
    ):
        # type: (...) -> Optional[Split]

        if not self.applies(universal_target, requirement):
            return None

        existing_requirement = self.requirements_by_project_name.setdefault(
            project_name, requirement
        )
        if existing_requirement == requirement:
            return None

        self.provenance.add(existing_requirement)

        provenance = OrderedSet(req for req in self.provenance if req != existing_requirement)
        provenance.add(requirement)

        requirements_by_project_name = self.requirements_by_project_name.copy()
        requirements_by_project_name[project_name] = requirement

        return Split(
            requirements_by_project_name=requirements_by_project_name, provenance=provenance
        )

    def requirement_configuration(
        self,
        unnamed_requirements,  # type: Iterable[ParsedRequirement]
        requirement_configuration,  # type: RequirementConfiguration
        network_configuration=None,  # type: Optional[NetworkConfiguration]
    ):
        # type: (...) -> RequirementConfiguration

        if not self.provenance:
            return requirement_configuration

        requirements = list(str(req) for req in unnamed_requirements)

        requirement_files = OrderedSet(
            os.path.realpath(requirement_file)
            for requirement_file in requirement_configuration.requirement_files
        )  # type: OrderedSet[Text]
        if requirement_files:
            provenance_by_project_name = {
                parsed_requirement.project_name: parsed_requirement
                for parsed_requirement in self.provenance
                if parsed_requirement.project_name
            }

            requirements_to_comment_out_by_source = defaultdict(
                list
            )  # type: DefaultDict[Text, List[ParsedRequirement]]
            for parsed_requirement in requirement_configuration.parse_requirements(
                network_configuration=network_configuration
            ):
                if not parsed_requirement.project_name:
                    continue

                provenance = provenance_by_project_name.get(parsed_requirement.project_name)
                if provenance and (parsed_requirement != provenance):
                    if parsed_requirement.line.source in requirement_files:
                        # We comment out the requirement
                        requirements_to_comment_out_by_source[
                            parsed_requirement.line.source
                        ].append(parsed_requirement)
                    else:
                        # We drop the requirement
                        pass
                elif parsed_requirement.line.source not in requirement_files:
                    requirements.append(str(parsed_requirement))
            if requirements_to_comment_out_by_source:
                new_requirement_files = OrderedSet()  # type: OrderedSet[Text]
                for source, parsed_requirements in requirements_to_comment_out_by_source.items():
                    if source in requirement_files:
                        new_requirement_files.add(
                            _comment_out_requirements(source, parsed_requirements)
                        )
                    else:
                        new_requirement_files.add(source)
                requirement_files = new_requirement_files
        else:
            requirements.extend(str(req) for req in self.requirements_by_project_name.values())

        return RequirementConfiguration(
            requirements=tuple(requirements),
            requirement_files=tuple(requirement_files),
            constraint_files=requirement_configuration.constraint_files,
        )


def calculate_download_input(
    targets,  # type: Targets
    requirement_configuration,  # type: RequirementConfiguration
    network_configuration,  # type: NetworkConfiguration
    repos_configuration,  # type: ReposConfiguration
    universal_target=None,  # type: Optional[UniversalTarget]
):
    # type: (...) -> DownloadInput

    direct_requirements = requirement_configuration.parse_requirements(network_configuration)
    if not universal_target:
        return DownloadInput(
            download_requests=tuple(
                DownloadRequest.create(
                    target=target, requirement_configuration=requirement_configuration
                )
                for target in targets.unique_targets()
            ),
            direct_requirements=direct_requirements,
        )

    target = LocalInterpreter.create(targets.interpreter)
    split_markers = _calculate_split_markers(
        requirement_configuration, network_configuration, repos_configuration
    )
    if not split_markers:
        return DownloadInput(
            download_requests=tuple(
                [
                    DownloadRequest.create(
                        target=target,
                        universal_target=universal_target,
                        requirement_configuration=requirement_configuration,
                    )
                ]
            ),
            direct_requirements=direct_requirements,
        )

    named_requirements = (
        OrderedDict()
    )  # type: OrderedDict[ProjectName, OrderedSet[ParsedRequirement]]
    unnamed_requirements = OrderedSet()  # type: OrderedSet[ParsedRequirement]
    for direct_requirement in direct_requirements:
        if direct_requirement.project_name:
            named_requirements.setdefault(direct_requirement.project_name, OrderedSet()).add(
                direct_requirement
            )
        else:
            unnamed_requirements.add(direct_requirement)

    requirement_splits_by_universal_target = defaultdict(
        lambda: [Split()]
    )  # type: DefaultDict[UniversalTarget, List[Split]]
    for universal_target in _iter_universal_targets(universal_target, split_markers):
        marker_env = universal_target.marker_env()
        requirement_splits = requirement_splits_by_universal_target[universal_target]
        for project_name, remote_requirements in named_requirements.items():
            for requirement_split in list(requirement_splits):
                for remote_requirement in remote_requirements:
                    if remote_requirement.marker and not marker_env.evaluate(
                        remote_requirement.marker
                    ):
                        continue
                    new_split = requirement_split.add(
                        universal_target, project_name, remote_requirement
                    )
                    if new_split:
                        requirement_splits.append(new_split)

    download_requests = []
    for universal_target, splits in requirement_splits_by_universal_target.items():
        if len(splits) == 1:
            download_requests.append(
                DownloadRequest.create(
                    target=target,
                    universal_target=universal_target,
                    requirement_configuration=splits[0].requirement_configuration(
                        unnamed_requirements,
                        requirement_configuration,
                        network_configuration=network_configuration,
                    ),
                )
            )
            continue

        for split in splits:
            download_requests.append(
                DownloadRequest.create(
                    target=target,
                    universal_target=attr.evolve(
                        universal_target,
                        extra_markers=ExtraMarkers.extract(
                            (requirement.marker, str(requirement))
                            for requirement in split.provenance
                            if requirement.marker
                        ),
                    ),
                    requirement_configuration=split.requirement_configuration(
                        unnamed_requirements,
                        requirement_configuration,
                        network_configuration=network_configuration,
                    ),
                    provenance="split by {requirements} {reqs}".format(
                        requirements=pluralize(split.provenance, "requirement"),
                        reqs=", ".join("'{req}'".format(req=req) for req in split.provenance),
                    ),
                )
            )

    return DownloadInput(
        download_requests=tuple(download_requests), direct_requirements=direct_requirements
    )
