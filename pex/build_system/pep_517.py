# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
from subprocess import CalledProcessError
from textwrap import dedent

from pex import third_party
from pex.build_system.pep_518 import BuildSystem, load_build_system
from pex.dist_metadata import Distribution
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve.resolvers import Resolver
from pex.result import Error
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.util import named_temporary_file

if TYPE_CHECKING:
    from typing import Dict, Union

_DEFAULT_BUILD_BACKEND = "setuptools.build_meta:__legacy__"
_DEFAULT_BUILD_SYSTEMS = {}  # type: Dict[PipVersionValue, BuildSystem]


def _default_build_system(
    pip_version,  # type: PipVersionValue
    resolver,  # type: Resolver
):
    # type: (...) -> BuildSystem
    global _DEFAULT_BUILD_SYSTEMS
    build_system = _DEFAULT_BUILD_SYSTEMS.get(pip_version)
    if build_system is None:
        with TRACER.timed(
            "Building {build_backend} build_backend PEX".format(
                build_backend=_DEFAULT_BUILD_BACKEND
            )
        ):
            extra_env = {}  # type: Dict[str, str]
            if pip_version is PipVersion.VENDORED:
                requires = ["setuptools"]
                resolved = tuple(
                    Distribution.load(dist_location)
                    for dist_location in third_party.expose(requires)
                )
                extra_env.update(__PEX_UNVENDORED__="1")
            else:
                requires = [pip_version.setuptools_requirement]
                resolved = tuple(
                    installed_distribution.fingerprinted_distribution.distribution
                    for installed_distribution in resolver.resolve_requirements(
                        requires
                    ).installed_distributions
                )
            build_system = BuildSystem.create(
                requires=requires,
                resolved=resolved,
                build_backend=_DEFAULT_BUILD_BACKEND,
                **extra_env
            )
            _DEFAULT_BUILD_SYSTEMS[pip_version] = build_system
    return build_system


def _get_build_system(
    pip_version,  # type: PipVersionValue
    resolver,  # type: Resolver
    project_directory,  # type: str
):
    # type: (...) -> Union[BuildSystem, Error]
    custom_build_system_or_error = load_build_system(resolver, project_directory)
    if custom_build_system_or_error:
        return custom_build_system_or_error
    return _default_build_system(pip_version=pip_version, resolver=resolver)


def build_sdist(
    project_directory,  # type: str
    dist_dir,  # type: str
    pip_version,  # type: PipVersionValue
    resolver,  # type: Resolver
):
    # type: (...) -> Union[str, Error]
    if not os.path.exists(project_directory):
        return Error(
            "Project directory {project_directory} does not exist.".format(
                project_directory=project_directory
            )
        )
    if not os.path.isdir(project_directory):
        return Error(
            "Project directory {project_directory} is not a directory.".format(
                project_directory=project_directory
            )
        )

    build_system_or_error = _get_build_system(pip_version, resolver, project_directory)
    if isinstance(build_system_or_error, Error):
        return build_system_or_error
    build_system = build_system_or_error

    # The interface is spec'd here: https://peps.python.org/pep-0517/#build-sdist
    build_backend_module, _, _ = build_system.build_backend.partition(":")
    build_backend_object = build_system.build_backend.replace(":", ".")
    with named_temporary_file(mode="r") as fp:
        args = build_system.venv_pex.execute_args(
            "-c",
            dedent(
                """\
                import {build_backend_module}


                sdist_relpath = {build_backend_object}.build_sdist({dist_dir!r})
                with open({result_file!r}, "w") as fp:
                    fp.write(sdist_relpath)
                """
            ).format(
                build_backend_module=build_backend_module,
                build_backend_object=build_backend_object,
                dist_dir=dist_dir,
                result_file=fp.name,
            ),
        )
        try:
            subprocess.check_output(
                args=args, env=build_system.env, cwd=project_directory, stderr=subprocess.STDOUT
            )
        except CalledProcessError as e:
            return Error(
                "Failed to build sdist for local project {project_directory}: {err}\n"
                "{stderr}".format(project_directory=project_directory, err=e, stderr=e.output)
            )
        sdist_relpath = cast(str, fp.read()).strip()
    return os.path.join(dist_dir, sdist_relpath)
