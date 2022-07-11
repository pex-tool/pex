# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path

from pex.dist_metadata import Distribution
from pex.pex import PEX
from pex.pex_bootstrapper import ensure_venv
from pex.pex_builder import PEXBuilder
from pex.resolve.resolvers import Resolver
from pex.result import Error
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.venv.bin_path import BinPath

if TYPE_CHECKING:
    from typing import Iterable, Mapping, Optional, Tuple, Union

    import attr  # vendor:skip
    import toml  # vendor:skip
else:
    from pex.third_party import attr, toml


@attr.s(frozen=True)
class BuildSystemTable(object):
    requires = attr.ib()  # type: Tuple[str, ...]
    build_backend = attr.ib()  # type: str


def _read_build_system_table(
    pyproject_toml,  # type: str
):
    # type: (...) -> Union[Optional[BuildSystemTable], Error]
    try:
        with open(pyproject_toml) as fp:
            data = toml.load(fp)
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
    return BuildSystemTable(requires=tuple(requires), build_backend=build_system["build-backend"])


@attr.s(frozen=True)
class BuildSystem(object):
    @classmethod
    def create(
        cls,
        requires,  # type: Iterable[str]
        resolved,  # type: Iterable[Distribution]
        build_backend,  # type: str
        **extra_env  # type: str
    ):
        # type: (...) -> BuildSystem
        pex_builder = PEXBuilder()
        pex_builder.info.venv = True
        pex_builder.info.venv_site_packages_copies = True
        pex_builder.info.venv_bin_path = BinPath.PREPEND
        for req in requires:
            pex_builder.add_requirement(req)
        for dist in resolved:
            pex_builder.add_distribution(dist)
        pex_builder.freeze(bytecode_compile=False)
        pex = ensure_venv(PEX(pex_builder.path()))

        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)

        return cls(pex=pex, build_backend=build_backend, requires=tuple(requires), env=env)

    pex = attr.ib()  # type: str
    build_backend = attr.ib()  # type: str
    requires = attr.ib()  # type: Tuple[str, ...]
    env = attr.ib()  # type: Mapping[str, str]


def load_build_system(
    resolver,  # type: Resolver
    project_directory,  # type: str
):
    # type: (...) -> Union[Optional[BuildSystem], Error]

    # The interface is spec'd here: https://peps.python.org/pep-0518/
    pyproject_toml = os.path.join(project_directory, "pyproject.toml")
    if not os.path.isfile(pyproject_toml):
        return None

    maybe_build_system_table_or_error = _read_build_system_table(pyproject_toml)
    if not isinstance(maybe_build_system_table_or_error, BuildSystemTable):
        return maybe_build_system_table_or_error
    build_system_table = maybe_build_system_table_or_error

    with TRACER.timed(
        "Building {build_backend} build_backend PEX".format(
            build_backend=build_system_table.build_backend
        )
    ):
        result = resolver.resolve_requirements(requirements=build_system_table.requires)
        return BuildSystem.create(
            requires=build_system_table.requires,
            resolved=tuple(
                installed_distribution.distribution
                for installed_distribution in result.installed_distributions
            ),
            build_backend=build_system_table.build_backend,
        )
