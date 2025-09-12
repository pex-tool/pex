# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import os

from pex.auth import PasswordEntry
from pex.dist_metadata import Requirement, RequirementParseError
from pex.pep_503 import ProjectName
from pex.pep_508 import MarkerEnvironment
from pex.resolve.target_system import MarkerEnv, UniversalTarget
from pex.third_party.packaging.markers import InvalidMarker, Marker
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict, Iterable, Optional, Tuple, Union

    import attr  # vendor:skip

else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Scope(object):
    @classmethod
    def parse(cls, value):
        # type: (str) -> Scope

        if not value:
            return Scope()

        def create_invalid_error(footer=None):
            # type: (Optional[str]) -> Exception
            error_msg_lines = [
                "The given scope is invalid: {scope}".format(scope=value),
                "Expected a bare project name, a bare marker or a project name and marker; "
                "e.g.: `torch; sys_platform != 'darwin'`.",
            ]
            if footer:
                error_msg_lines.append(footer)
            return ValueError(os.linesep.join(error_msg_lines))

        try:
            return cls(marker=Marker(value))
        except InvalidMarker:
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

    project = attr.ib(default=None)  # type: Optional[ProjectName]
    marker = attr.ib(default=None)  # type: Optional[Marker]

    def in_scope(
        self,
        target,  # type: Union[Dict[str, str], MarkerEnv, MarkerEnvironment, UniversalTarget]
        project_name=None,  # type: Optional[str]
    ):
        # type: (...) -> bool

        if self.marker:
            if isinstance(target, dict) and not self.marker.evaluate(target):
                return False
            elif isinstance(target, MarkerEnv) and not target.evaluate(self.marker):
                return False
            elif isinstance(target, MarkerEnvironment) and not self.marker.evaluate(
                target.as_dict()
            ):
                return False
            elif isinstance(target, UniversalTarget) and not target.marker_env().evaluate(
                self.marker
            ):
                return False

        if project_name and self.project and self.project != ProjectName(project_name):
            return False

        return True

    def __str__(self):
        # type: () -> str
        if self.project and self.marker:
            return "{project}; {marker}".format(project=self.project, marker=self.marker)
        if self.project:
            return str(self.project)
        if self.marker:
            return str(self.marker)
        return ""


# Indexes that only contain certain non-public projects or else projects you wish to override:
# Scope(project=ProjectName("my-company-project1")) for https://my.company/simple

# Platform-specific indexes that have native wheels built for just that platform:
# Scope(marker=Marker("platform_machine == 'armv7l'")) for https://www.piwheels.org/simple

# Complex cases, like PyTorch:
# Scope(project=ProjectName("torch"), marker=Marker("sys_platform != 'darwin'")) for
# https://download.pytorch.org/whl/cu129


@attr.s(frozen=True)
class Repo(object):
    @classmethod
    def from_dict(cls, data):
        # type: (Dict[str, Any]) -> Repo

        # TODO: XXX: Error handling
        return cls(
            location=data["location"], scopes=tuple(Scope.parse(scope) for scope in data["scopes"])
        )

    location = attr.ib()  # type: str
    scopes = attr.ib(default=())  # type: Tuple[Scope, ...]

    def as_dict(self):
        # type: () -> Dict[str, Any]
        return {"location": self.location, "scopes": [str(scope) for scope in self.scopes]}

    def in_scope(
        self,
        target,  # type: Union[Dict[str, str], MarkerEnv, MarkerEnvironment, UniversalTarget]
        project_name=None,  # type: Optional[str]
    ):
        # type: (...) -> bool
        if not self.scopes:
            return True
        return any(scope.in_scope(target, project_name=project_name) for scope in self.scopes)


PYPI = "https://pypi.org/simple"


@attr.s(frozen=True)
class ReposConfiguration(object):
    @classmethod
    def create(
        cls,
        indexes=(),  # type: Iterable[Repo]
        find_links=(),  # type: Iterable[Repo]
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
        )

    index_repos = attr.ib(default=(Repo(PYPI),))  # type: Tuple[Repo, ...]
    find_links_repos = attr.ib(default=())  # type: Tuple[Repo, ...]
    password_entries = attr.ib(default=())  # type: Tuple[PasswordEntry, ...]

    @property
    def indexes(self):
        # type: () -> Tuple[str, ...]
        return tuple(repo.location for repo in self.index_repos if not repo.scopes)

    @property
    def find_links(self):
        # type: () -> Tuple[str, ...]
        return tuple(repo.location for repo in self.find_links_repos if not repo.scopes)

    def scoped(self, target):
        # type: (Union[Dict[str, str], MarkerEnv, MarkerEnvironment, UniversalTarget]) -> ReposConfiguration
        return ReposConfiguration.create(
            indexes=[index for index in self.index_repos if index.in_scope(target)],
            find_links=[
                find_links for find_links in self.find_links_repos if find_links.in_scope(target)
            ],
        )
