# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools

from pex.auth import PasswordEntry
from pex.enum import Enum
from pex.jobs import DEFAULT_MAX_JOBS
from pex.network_configuration import NetworkConfiguration
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable, Iterable, Optional, Tuple, Union

    import attr  # vendor:skip

    from pex.resolve.lockfile.model import Lockfile
    from pex.result import Error
else:
    from pex.third_party import attr


PYPI = "https://pypi.org/simple"


class ResolverVersion(Enum["ResolverVersion.Value"]):
    class Value(Enum.Value):
        pass

    PIP_LEGACY = Value("pip-legacy-resolver")
    PIP_2020 = Value("pip-2020-resolver")


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
            indexes=tuple(indexes),
            find_links=tuple(find_links),
            password_entries=tuple(password_entries),
        )

    indexes = attr.ib(default=(PYPI,))  # type: Tuple[str, ...]
    find_links = attr.ib(default=())  # type: Tuple[str, ...]
    password_entries = attr.ib(default=())  # type: Tuple[PasswordEntry, ...]


@attr.s(frozen=True)
class PipConfiguration(object):
    resolver_version = attr.ib(default=ResolverVersion.PIP_LEGACY)  # type: ResolverVersion.Value
    repos_configuration = attr.ib(default=ReposConfiguration())  # type: ReposConfiguration
    network_configuration = attr.ib(default=NetworkConfiguration())  # type: NetworkConfiguration
    allow_prereleases = attr.ib(default=False)  # type: bool
    allow_wheels = attr.ib(default=True)  # type: bool
    allow_builds = attr.ib(default=True)  # type: bool
    prefer_older_binary = attr.ib(default=False)  # type: bool
    use_pep517 = attr.ib(default=None)  # type: Optional[bool]
    build_isolation = attr.ib(default=True)  # type: bool
    transitive = attr.ib(default=True)  # type: bool
    max_jobs = attr.ib(default=DEFAULT_MAX_JOBS)  # type: int
    preserve_log = attr.ib(default=False)  # type: bool


@attr.s(frozen=True)
class PexRepositoryConfiguration(object):
    pex_repository = attr.ib()  # type: str
    network_configuration = attr.ib(default=NetworkConfiguration())  # type: NetworkConfiguration
    transitive = attr.ib(default=True)  # type: bool


@attr.s(frozen=True)
class LockRepositoryConfiguration(object):
    parse_lock = attr.ib()  # type: Callable[[], Union[Lockfile, Error]]
    pip_configuration = attr.ib()  # type: PipConfiguration
