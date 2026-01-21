# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import os
import re
from collections import OrderedDict, defaultdict

from pex.auth import PasswordEntry
from pex.compatibility import string
from pex.dist_metadata import Requirement, RequirementParseError
from pex.exceptions import production_assert, reportable_unexpected_error_msg
from pex.fetcher import URLFetcher
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.requirements import (
    FindLinks,
    Index,
    PyPIRequirement,
    URLRequirement,
    VCSRequirement,
    parse_requirement_file,
)
from pex.resolve.target_system import MarkerEnv
from pex.third_party.packaging.markers import InvalidMarker, Marker
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    # N.B.: The `re.Pattern` type is not available in all Python versions Pex supports.
    from re import Pattern  # type: ignore[attr-defined]
    from typing import Any, DefaultDict, Dict, Iterable, List, Mapping, Optional, Text, Tuple, Union

    import attr  # vendor:skip

else:
    from pex.third_party import attr


@attr.s(frozen=True, eq=False, hash=False)
class Scope(object):
    @classmethod
    def _parse_regex_forms(cls, value):
        # type: (str) -> Optional[Scope]

        project_spec, sep, marker_value = value.partition(";")
        try:
            project = ProjectName(
                project_spec, validated=True
            )  # type: Union[ProjectName, Pattern[str]]
        except ProjectName.InvalidError:
            try:
                project = re.compile(project_spec)
            except re.error:
                return None

        marker = None  # type: Optional[Marker]
        if marker_value:
            try:
                marker = Marker(marker_value)
            except InvalidMarker:
                return None
        return cls(project=project, marker=marker)

    @classmethod
    def parse(cls, value):
        # type: (str) -> Scope

        if not value:
            return Scope()

        def create_invalid_error(footer=None):
            # type: (Optional[str]) -> Exception
            error_msg_lines = [
                "The given scope is invalid: {scope}".format(scope=value),
                "Expected a bare project name-or-regex, a bare marker or a project name-or-regex "
                "and marker; e.g.: `torch; sys_platform != 'darwin'`.",
            ]
            if footer:
                error_msg_lines.append(footer)
            return ValueError(os.linesep.join(error_msg_lines))

        try:
            return cls(marker=Marker(value))
        except InvalidMarker:
            scope = cls._parse_regex_forms(value)
            if scope:
                return scope

            try:
                requirement = Requirement.parse(value)
            except RequirementParseError:
                raise create_invalid_error()
            if requirement.extras:
                raise create_invalid_error(
                    "The specified project name {project_name} has extras that should be removed: "
                    "{extras}".format(
                        project_name=requirement.project_name.raw,
                        extras=", ".join(sorted(requirement.extras)),
                    )
                )
            if requirement.specifier:
                raise create_invalid_error(
                    "The specified project name {project_name} has a version specifier that should "
                    "be removed: {specifier}".format(
                        project_name=requirement.project_name.raw, specifier=requirement.specifier
                    )
                )
            return cls(project=requirement.project_name, marker=requirement.marker)

    project = attr.ib(default=None)  # type: Optional[Union[ProjectName, Pattern[str]]]
    marker = attr.ib(default=None)  # type: Optional[Marker]

    def in_scope(
        self,
        target_env,  # type: Union[Dict[str, str], MarkerEnv]
        project_name=None,  # type: Optional[ProjectName]
    ):
        # type: (...) -> bool

        if self.marker:
            if isinstance(target_env, dict) and not self.marker.evaluate(target_env):
                return False
            elif isinstance(target_env, MarkerEnv) and not target_env.evaluate(self.marker):
                return False

        if not self.project or not project_name:
            return True

        if isinstance(self.project, ProjectName):
            return self.project == project_name

        return cast("Pattern", self.project).match(project_name.normalized) is not None

    def _tup(self):
        # type: () -> Tuple[Optional[str], Optional[str]]

        project = None  # type: Optional[str]
        if isinstance(self.project, ProjectName):
            project = self.project.normalized
        elif self.project:
            # N.B.: The object returned from older versions of Python's `re.compile` do not
            # implement __eq__; so we use the input pattern string as a proxy.
            project = self.project.pattern

        marker = None  # type: Optional[str]
        if self.marker:
            # N.B.: Older versions of `Marker` do not implement __eq__; so we use str(...) as a
            # proxy.
            marker = str(self.marker)

        return project, marker

    def __hash__(self):
        # type: () -> int
        return hash(self._tup())

    def __eq__(self, other):
        # type: (Any) -> bool

        if not isinstance(other, Scope):
            return NotImplemented

        return self._tup() == other._tup()

    def __ne__(self, other):
        return not self == other

    def __str__(self):
        # type: () -> str

        project_as_str = None  # type: Optional[str]
        if isinstance(self.project, ProjectName):
            project_as_str = self.project.raw
        elif self.project:
            project_as_str = self.project.pattern

        if project_as_str and self.marker:
            return "{project}; {marker}".format(project=project_as_str, marker=self.marker)
        if project_as_str:
            return project_as_str
        if self.marker:
            return str(self.marker)
        return ""


@attr.s(frozen=True)
class Repo(object):
    @classmethod
    def from_dict(cls, data):
        # type: (Dict[str, Any]) -> Repo
        return cls(
            location=data["location"], scopes=tuple(Scope.parse(scope) for scope in data["scopes"])
        )

    location = attr.ib()  # type: Text
    scopes = attr.ib(default=())  # type: Tuple[Scope, ...]

    def as_dict(self):
        # type: () -> Dict[str, Any]
        return {"location": self.location, "scopes": [str(scope) for scope in self.scopes]}

    def in_scope(
        self,
        target_env,  # type: Union[Dict[str, str], MarkerEnv]
        project_name=None,  # type: Optional[ProjectName]
    ):
        # type: (...) -> bool
        if not self.scopes:
            return True
        return any(scope.in_scope(target_env, project_name=project_name) for scope in self.scopes)


PYPI = "https://pypi.org/simple"


@attr.s(frozen=True)
class PackageRepositories(object):
    @classmethod
    def from_dict(cls, data):
        # type: (Dict[str, Any]) -> PackageRepositories

        markers = data.get("markers")
        universal_markers_data = data.get("universal_markers")
        production_assert(bool(markers) ^ bool(universal_markers_data))
        if markers:
            if not isinstance(markers, dict) or not all(
                isinstance(key, string) and isinstance(value, string)
                for key, value in markers.items()
            ):
                raise AssertionError(reportable_unexpected_error_msg())
            target_env = markers  # type: Union[Dict[str, str], MarkerEnv]
        else:
            if not isinstance(universal_markers_data, dict) or not all(
                isinstance(key, string) for key in universal_markers_data
            ):
                raise AssertionError(reportable_unexpected_error_msg())
            target_env = MarkerEnv.from_dict(universal_markers_data)

        return cls(
            target_env=target_env,
            global_indexes=tuple(data["global_indexes"]),
            global_find_links=tuple(data["global_find_links"]),
            scoped_indexes=tuple(Repo.from_dict(index) for index in data["scoped_indexes"]),
            scoped_find_links=tuple(
                Repo.from_dict(find_links) for find_links in data["scoped_find_links"]
            ),
        )

    _target_env = attr.ib()  # type: Union[Dict[str, str], MarkerEnv]
    _scoped_indexes = attr.ib(default=())  # type: Tuple[Repo, ...]
    _scoped_find_links = attr.ib(default=())  # type: Tuple[Repo, ...]
    global_indexes = attr.ib(default=(Repo(PYPI),))  # type: Tuple[Text, ...]
    global_find_links = attr.ib(default=())  # type: Tuple[Text, ...]

    @property
    def has_scoped_repositories(self):
        # type: () -> bool
        return len(self._scoped_indexes) > 0 or len(self._scoped_find_links) > 0

    def as_dict(self):
        # type: () -> Dict[str, Any]
        return {
            "markers": self._target_env if isinstance(self._target_env, dict) else None,
            "universal_markers": (
                self._target_env.as_dict() if isinstance(self._target_env, MarkerEnv) else None
            ),
            "global_indexes": list(self.global_indexes),
            "global_find_links": list(self.global_find_links),
            "scoped_indexes": [index.as_dict() for index in self._scoped_indexes],
            "scoped_find_links": [find_links.as_dict() for find_links in self._scoped_find_links],
        }

    def _in_scope_repos(
        self,
        scoped_repos,  # type: Iterable[Repo]
        project_name,  # type: ProjectName
    ):
        # type: (...) -> List[Text]
        return [
            repo.location
            for repo in scoped_repos
            if repo.in_scope(target_env=self._target_env, project_name=project_name)
        ]

    def in_scope_indexes(self, project_name):
        # type: (ProjectName) -> List[Text]
        return self._in_scope_repos(scoped_repos=self._scoped_indexes, project_name=project_name)

    def in_scope_find_links(self, project_name):
        # type: (ProjectName) -> List[Text]
        return self._in_scope_repos(scoped_repos=self._scoped_find_links, project_name=project_name)


@attr.s(frozen=True)
class ReposConfiguration(object):
    @classmethod
    def create(
        cls,
        indexes=(),  # type: Iterable[Repo]
        find_links=(),  # type: Iterable[Repo]
        derive_scopes_from_requirements_files=False,  # type: bool
    ):
        # type: (...) -> ReposConfiguration
        password_entries = []
        for repo in itertools.chain(indexes, find_links):
            password_entry = PasswordEntry.maybe_extract_from_url(repo.location)
            if password_entry:
                password_entries.append(password_entry)

        return cls(
            index_repos=tuple(indexes),
            find_links_repos=tuple(find_links),
            password_entries=tuple(password_entries),
            derive_scopes_from_requirements_files=derive_scopes_from_requirements_files,
        )

    index_repos = attr.ib(default=(Repo(PYPI),))  # type: Tuple[Repo, ...]
    find_links_repos = attr.ib(default=())  # type: Tuple[Repo, ...]
    password_entries = attr.ib(default=())  # type: Tuple[PasswordEntry, ...]
    derive_scopes_from_requirements_files = attr.ib(default=False)  # type: bool

    def with_contained_repos(
        self,
        requirement_files=None,  # type: Optional[Iterable[Text]]
        fetcher=None,  # type: Optional[URLFetcher]
    ):
        # type: (...) -> ReposConfiguration

        if not requirement_files:
            return self

        indexes_by_source = OrderedDict()  # type: OrderedDict[Text, OrderedSet[Text]]
        find_links_by_source = OrderedDict()  # type: OrderedDict[Text, OrderedSet[Text]]
        scopes_by_source = defaultdict(OrderedSet)  # type: DefaultDict[Text, OrderedSet[Scope]]
        for item in itertools.chain.from_iterable(
            parse_requirement_file(requirement_file, fetcher=fetcher)
            for requirement_file in requirement_files
        ):
            if self.derive_scopes_from_requirements_files and isinstance(
                item, (PyPIRequirement, URLRequirement, VCSRequirement)
            ):
                scopes_by_source[item.line.source].add(
                    Scope(project=item.requirement.project_name, marker=item.requirement.marker)
                )
            elif isinstance(item, FindLinks):
                find_links_by_source.setdefault(item.line.source, OrderedSet()).add(item.location)
            elif isinstance(item, Index):
                indexes_by_source.setdefault(item.line.source, OrderedSet()).add(item.location)

        if not indexes_by_source and not find_links_by_source:
            return self

        def merge_scopes(
            repos,  # type: Iterable[Repo]
            locations_by_source,  # type: Mapping[Text, Iterable[Text]]
        ):
            scopes_by_location = OrderedDict(
                (repo.location, OrderedSet(repo.scopes)) for repo in repos
            )
            for source, locations in locations_by_source.items():
                for location in locations:
                    scopes_by_location.setdefault(location, OrderedSet()).update(
                        scopes_by_source[source]
                    )
            return tuple(
                Repo(location=location, scopes=tuple(scopes))
                for location, scopes in scopes_by_location.items()
            )

        return attr.evolve(
            self,
            index_repos=merge_scopes(repos=self.index_repos, locations_by_source=indexes_by_source),
            find_links_repos=merge_scopes(
                repos=self.find_links_repos, locations_by_source=find_links_by_source
            ),
        )

    @property
    def indexes(self):
        # type: () -> Tuple[Text, ...]
        return tuple(repo.location for repo in self.index_repos if not repo.scopes)

    @property
    def find_links(self):
        # type: () -> Tuple[Text, ...]
        return tuple(repo.location for repo in self.find_links_repos if not repo.scopes)

    def scoped(self, target_env):
        # type: (Union[Dict[str, str], MarkerEnv]) -> PackageRepositories
        return PackageRepositories(
            target_env=target_env,
            global_indexes=self.indexes,
            global_find_links=self.find_links,
            scoped_indexes=tuple(
                index
                for index in self.index_repos
                if index.scopes and index.in_scope(target_env=target_env)
            ),
            scoped_find_links=tuple(
                find_links
                for find_links in self.find_links_repos
                if find_links.scopes and find_links.in_scope(target_env=target_env)
            ),
        )
