# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools

from pex.auth import PasswordEntry
from pex.pep_503 import ProjectName
from pex.pep_508 import MarkerEnvironment
from pex.resolve.target_system import MarkerEnv, UniversalTarget
from pex.third_party.packaging.markers import Marker
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, Iterable, Optional, Tuple, Union

    import attr  # vendor:skip

else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Scope(object):
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
        indexes=(),  # type: Iterable[str]
        find_links=(),  # type: Iterable[str]
    ):
        # type: (...) -> ReposConfiguration
        password_entries = []
        for url in itertools.chain(indexes, find_links):
            password_entry = PasswordEntry.maybe_extract_from_url(url)
            if password_entry:
                password_entries.append(password_entry)

        return cls(
            indexes=tuple(Repo(index) for index in indexes),
            find_links=tuple(Repo(find_links_repo) for find_links_repo in find_links),
            password_entries=tuple(password_entries),
        )

    _indexes = attr.ib(default=(Repo(PYPI),))  # type: Tuple[Repo, ...]
    _find_links = attr.ib(default=())  # type: Tuple[Repo, ...]
    password_entries = attr.ib(default=())  # type: Tuple[PasswordEntry, ...]

    @property
    def indexes(self):
        # type: () -> Tuple[str, ...]
        return tuple(repo.location for repo in self._indexes)

    @property
    def find_links(self):
        # type: () -> Tuple[str, ...]
        return tuple(repo.location for repo in self._find_links)
