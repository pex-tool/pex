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
    from typing import Dict, Iterable, Optional, Tuple, Union

    import attr  # vendor:skip

else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Scope(object):
    @classmethod
    def parse(cls, value):
        # type: (str) -> Scope

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
        project_name,  # type: str
        target,  # type: Union[Dict[str, str], MarkerEnv, MarkerEnvironment, UniversalTarget]
    ):
        # type: (...) -> bool

        if self.project and self.project != ProjectName(project_name):
            return False

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

        return True


# Indexes that only contain certain non-public projects or else projects you wish to override:
# Scope(project=ProjectName("my-company-project1")) for https://my.company/simple

# Platform-specific indexes that have native wheels built for just that platform:
# Scope(marker=Marker("platform_machine == 'armv7l'")) for https://www.piwheels.org/simple

# Complex cases, like PyTorch:
# Scope(project=ProjectName("torch"), marker=Marker("sys_platform != 'darwin'")) for
# https://download.pytorch.org/whl/cu129


@attr.s(frozen=True)
class Repo(object):
    location = attr.ib()  # type: str
    scopes = attr.ib(default=())  # type: Tuple[Scope, ...]

    def in_scope(
        self,
        project_name,  # type: str
        target,  # type: Union[Dict[str, str], MarkerEnv, MarkerEnvironment, UniversalTarget]
    ):
        # type: (...) -> bool
        if not self.scopes:
            return True
        return any(scope.in_scope(project_name, target) for scope in self.scopes)


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
            indexes=tuple(indexes),
            find_links=tuple(find_links),
            password_entries=tuple(password_entries),
        )

    _indexes = attr.ib(default=(Repo(PYPI),))  # type: Tuple[Repo, ...]
    _find_links = attr.ib(default=())  # type: Tuple[Repo, ...]
    password_entries = attr.ib(default=())  # type: Tuple[PasswordEntry, ...]

    @property
    def indexes(self):
        # type: () -> Tuple[str, ...]
        return tuple(repo.location for repo in self._indexes if not repo.scopes)

    @property
    def find_links(self):
        # type: () -> Tuple[str, ...]
        return tuple(repo.location for repo in self._find_links if not repo.scopes)
