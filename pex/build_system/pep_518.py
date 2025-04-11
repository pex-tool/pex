# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path

from pex import toml
from pex.build_system import (
    DEFAULT_BUILD_BACKEND,
    DEFAULT_BUILD_SYSTEM_TABLE,
    BuildSystem,
    BuildSystemTable,
)
from pex.resolve.resolvers import Resolver
from pex.result import Error
from pex.targets import LocalInterpreter, Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Optional, Union


def _read_build_system_table(
    pyproject_toml,  # type: str
):
    # type: (...) -> Union[Optional[BuildSystemTable], Error]
    try:
        data = toml.load(pyproject_toml)
    except toml.TomlDecodeError as e:
        return Error(
            "Problem parsing toml in {pyproject_toml}: {err}".format(
                pyproject_toml=pyproject_toml, err=e
            )
        )

    build_system = data.get("build-system")
    if not build_system:
        return None

    requires = build_system.get("requires")
    if not requires:
        return None

    return BuildSystemTable(
        requires=tuple(requires),
        build_backend=build_system.get("build-backend", DEFAULT_BUILD_BACKEND),
        backend_path=tuple(
            os.path.join(os.path.dirname(pyproject_toml), entry)
            for entry in build_system.get("backend-path", ())
        ),
    )


def _maybe_load_build_system_table(project_directory):
    # type: (str) -> Union[Optional[BuildSystemTable], Error]

    # The interface is spec'd here: https://peps.python.org/pep-0518/
    pyproject_toml = os.path.join(project_directory, "pyproject.toml")
    if not os.path.isfile(pyproject_toml):
        return None
    return _read_build_system_table(pyproject_toml)


def load_build_system_table(project_directory):
    # type: (str) -> Union[BuildSystemTable, Error]

    maybe_build_system_table_or_error = _maybe_load_build_system_table(project_directory)
    if maybe_build_system_table_or_error is not None:
        return maybe_build_system_table_or_error
    return DEFAULT_BUILD_SYSTEM_TABLE


def load_build_system(
    target,  # type: Target
    resolver,  # type: Resolver
    project_directory,  # type: str
    extra_requirements=None,  # type: Optional[Iterable[str]]
):
    # type: (...) -> Union[Optional[BuildSystem], Error]

    maybe_build_system_table_or_error = _maybe_load_build_system_table(project_directory)
    if not isinstance(maybe_build_system_table_or_error, BuildSystemTable):
        return maybe_build_system_table_or_error
    build_system_table = maybe_build_system_table_or_error

    with TRACER.timed(
        "Building {build_backend} build_backend PEX".format(
            build_backend=build_system_table.build_backend
        )
    ):
        result = resolver.resolve_requirements(
            targets=Targets.from_target(LocalInterpreter.create(target.get_interpreter())),
            requirements=build_system_table.requires,
        )
        return BuildSystem.create(
            interpreter=target.get_interpreter(),
            requires=build_system_table.requires,
            resolved=tuple(
                resolved_distribution.distribution for resolved_distribution in result.distributions
            ),
            build_backend=build_system_table.build_backend,
            backend_path=build_system_table.backend_path,
            extra_requirements=extra_requirements,
            use_system_time=resolver.use_system_time(),
        )
