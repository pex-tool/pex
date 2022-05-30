# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os.path
import pkgutil
import subprocess
from subprocess import CalledProcessError
from textwrap import dedent

from pex.common import atomic_directory
from pex.dist_metadata import Distribution
from pex.pex import PEX
from pex.pex_bootstrapper import ensure_venv
from pex.pex_builder import PEXBuilder
from pex.resolve.lockfile import json_codec
from pex.resolve.resolvers import Resolver
from pex.result import Error
from pex.third_party import isolated
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from pex.venv.bin_path import BinPath

if TYPE_CHECKING:
    from typing import Iterable, Mapping, Optional, Text, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def _execute_with_toml(
    resolver,  # type: Resolver
    script_contents,  # type: str
):
    # type: (...) -> Union[Text, Error]
    target_dir = os.path.join(ENV.PEX_ROOT, "tools", "toml.pex", isolated().pex_hash)
    with TRACER.timed("Building toml parsing PEX"):
        with atomic_directory(target_dir=target_dir, exclusive=True) as atomic_dir:
            if not atomic_dir.is_finalized():
                lock_file_contents = pkgutil.get_data(__name__, "toml-lock.json")
                assert lock_file_contents is not None, (
                    "The sibling resource toml-lock.json of {} should always be present in a "
                    "Pex distribution or source tree.".format(__name__)
                )
                contents = lock_file_contents.decode("utf-8")
                source = os.path.join(os.path.dirname(__file__), "toml-lock.json")
                lock = json_codec.loads(lockfile_contents=contents, source=source)

                # Our toml lock was created against the default public PyPI index; so we can only
                # use the lock if the resolve is also setup to use the default repos configuration
                # as well.
                if resolver.is_default_repos():
                    result = resolver.resolve_lock(lock=lock)
                else:
                    result = resolver.resolve_requirements(
                        requirements=[str(req) for req in lock.requirements]
                    )

                pex_builder = PEXBuilder(path=atomic_dir.work_dir)
                pex_builder.info.pex_root = ENV.PEX_ROOT
                pex_builder.info.venv = True
                for installed_distribution in result.installed_distributions:
                    pex_builder.add_distribution(installed_distribution.distribution)
                    for direct_req in installed_distribution.direct_requirements:
                        pex_builder.add_requirement(direct_req)
                pex_builder.freeze(bytecode_compile=False)

    try:
        return subprocess.check_output(
            args=[ensure_venv(PEX(target_dir)), "-c", script_contents]
        ).decode("utf-8")
    except CalledProcessError as e:
        return Error(str(e))


@attr.s(frozen=True)
class BuildSystemTable(object):
    requires = attr.ib()  # type: Tuple[str, ...]
    build_backend = attr.ib()  # type: str


def _read_build_system_table(
    resolver,  # type: Resolver
    pyproject_toml,  # type: str
):
    # type: (...) -> Union[Optional[BuildSystemTable], Error]
    output_or_error = _execute_with_toml(
        resolver,
        dedent(
            """\
        import json
        import sys

        import toml

        with open({pyproject_toml!r}) as fp:
            json.dump(toml.load(fp), sys.stdout)
        """
        ).format(pyproject_toml=os.path.abspath(pyproject_toml)),
    )
    if isinstance(output_or_error, Error):
        return output_or_error
    output = output_or_error

    data = json.loads(output)
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

    maybe_build_system_table_or_error = _read_build_system_table(resolver, pyproject_toml)
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
