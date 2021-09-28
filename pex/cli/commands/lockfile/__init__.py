# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex import resolver
from pex.cli.commands.lockfile.lockfile import Lockfile as Lockfile  # For re-export.
from pex.commands.command import Error
from pex.common import safe_open
from pex.requirements import LocalProjectRequirement
from pex.resolve.locked_resolve import LockConfiguration
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolve.target_configuration import TargetConfiguration
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from pex.version import __version__

if TYPE_CHECKING:
    from typing import List, Text, Union


class ParseError(Exception):
    """Indicates an error parsing a Pex lock file."""


def load(lockfile_path):
    # type: (str) -> Lockfile
    """Loads the Pex lock file stored at the given path.

    :param lockfile_path: The path to the Pex lock file to load.
    :return: The parsed lock file.
    :raises: :class:`ParseError` if there was a problem parsing the lock file.
    """
    from pex.cli.commands.lockfile import json_codec

    return json_codec.load(lockfile_path=lockfile_path)


def loads(
    lockfile_contents,  # type: Text
    source="<string>",  # type: str
):
    # type: (...) -> Lockfile
    """Parses the given Pex lock file contents.

    :param lockfile_contents: The contents of a Pex lock file.
    :param source: A descriptive name for the source of the lock file contents.
    :return: The parsed lock file.
    :raises: :class:`ParseError` if there was a problem parsing the lock file.
    """
    from pex.cli.commands.lockfile import json_codec

    return json_codec.loads(lockfile_contents=lockfile_contents, source=source)


def store(
    lockfile,  # type: Lockfile
    path,  # type: str
):
    # type: (...) -> None
    """Stores the given lock file at the given path.

    Any missing parent directories in the path will be created and any pre-existing file at the
    path wil be over-written.

    :param lockfile: The lock file to store.
    :param path: The path to store the lock file at.
    """
    import json
    from pex.cli.commands.lockfile import json_codec

    with safe_open(path, "w") as fp:
        json.dump(json_codec.as_json_data(lockfile), fp, sort_keys=True)


def create(
    lock_configuration,  # type: LockConfiguration
    requirement_configuration,  # type: RequirementConfiguration
    target_configuration,  # type: TargetConfiguration
    pip_configuration,  # type: PipConfiguration
):
    # type: (...) -> Union[Lockfile, Error]
    """Create a lock file for the given resolve configurations."""

    network_configuration = pip_configuration.network_configuration
    requirements = []  # type: List[Requirement]
    local_projects = []  # type: List[LocalProjectRequirement]
    for parsed_requirement in requirement_configuration.parse_requirements(network_configuration):
        if isinstance(parsed_requirement, LocalProjectRequirement):
            local_projects.append(parsed_requirement)
        else:
            requirements.append(parsed_requirement.requirement)
    if local_projects:
        return Error(
            "Cannot create a lock for local project requirements. Given {count}:\n"
            "{projects}".format(
                count=len(local_projects),
                projects="\n".join(
                    "{index}.) {project}".format(index=index, project=project.path)
                    for index, project in enumerate(local_projects, start=1)
                ),
            )
        )

    constraints = tuple(
        constraint.requirement
        for constraint in requirement_configuration.parse_constraints(network_configuration)
    )

    try:
        downloaded = resolver.download(
            requirements=requirement_configuration.requirements,
            requirement_files=requirement_configuration.requirement_files,
            constraint_files=requirement_configuration.constraint_files,
            allow_prereleases=pip_configuration.allow_prereleases,
            transitive=pip_configuration.transitive,
            interpreters=target_configuration.interpreters,
            platforms=target_configuration.platforms,
            indexes=pip_configuration.repos_configuration.indexes,
            find_links=pip_configuration.repos_configuration.find_links,
            resolver_version=pip_configuration.resolver_version,
            network_configuration=network_configuration,
            cache=ENV.PEX_ROOT,
            build=pip_configuration.allow_builds,
            use_wheel=pip_configuration.allow_wheels,
            assume_manylinux=target_configuration.assume_manylinux,
            max_parallel_jobs=pip_configuration.max_jobs,
            lock_configuration=lock_configuration,
            # We're just out for the lock data and not the distribution files downloaded to produce
            # that data.
            dest=None,
        )
    except resolver.ResolveError as e:
        return Error(str(e))

    return Lockfile.create(
        pex_version=__version__,
        style=lock_configuration.style,
        resolver_version=pip_configuration.resolver_version,
        requirements=requirements,
        constraints=constraints,
        allow_prereleases=pip_configuration.allow_prereleases,
        allow_wheels=pip_configuration.allow_wheels,
        allow_builds=pip_configuration.allow_builds,
        transitive=pip_configuration.transitive,
        locked_resolves=downloaded.locked_resolves,
    )
