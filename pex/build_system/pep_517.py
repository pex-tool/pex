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
from pex.resolve.resolvers import Resolver
from pex.result import Error
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.util import named_temporary_file

if TYPE_CHECKING:
    from typing import Optional, Union

_DEFAULT_BUILD_BACKEND = "setuptools.build_meta:__legacy__"
_DEFAULT_REQUIRES = ["setuptools"]
_DEFAULT_BUILD_SYSTEM = None  # type: Optional[BuildSystem]


def _default_build_system():
    # type: () -> BuildSystem
    global _DEFAULT_BUILD_SYSTEM
    if _DEFAULT_BUILD_SYSTEM is None:
        with TRACER.timed(
            "Building {build_backend} build_backend PEX".format(
                build_backend=_DEFAULT_BUILD_BACKEND
            )
        ):
            _DEFAULT_BUILD_SYSTEM = BuildSystem.create(
                requires=_DEFAULT_REQUIRES,
                resolved=tuple(
                    Distribution.load(dist_location)
                    for dist_location in third_party.expose(_DEFAULT_REQUIRES)
                ),
                build_backend=_DEFAULT_BUILD_BACKEND,
                __PEX_UNVENDORED__="1",
            )
    return _DEFAULT_BUILD_SYSTEM


def _get_build_system(
    resolver,  # type: Resolver
    project_directory,  # type: str
):
    # type: (...) -> Union[BuildSystem, Error]
    custom_build_system_or_error = load_build_system(resolver, project_directory)
    if custom_build_system_or_error:
        return custom_build_system_or_error
    return _default_build_system()


def build_sdist(
    project_directory,  # type: str
    dist_dir,  # type: str
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

    build_system_or_error = _get_build_system(resolver, project_directory)
    if isinstance(build_system_or_error, Error):
        return build_system_or_error
    build_system = build_system_or_error

    # The interface is spec'd here: https://peps.python.org/pep-0517/#build-sdist
    build_backend_module, _, _ = build_system.build_backend.partition(":")
    build_backend_object = build_system.build_backend.replace(":", ".")
    with named_temporary_file(mode="r") as fp:
        args = [
            build_system.pex,
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
        ]
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
