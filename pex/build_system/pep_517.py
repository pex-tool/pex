# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os
import subprocess
import sys
from textwrap import dedent

from pex import third_party
from pex.build_system import DEFAULT_BUILD_BACKEND
from pex.build_system.pep_518 import BuildSystem, load_build_system
from pex.common import safe_mkdtemp
from pex.dist_metadata import DistMetadata, Distribution
from pex.jobs import Job, SpawnedJob
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve.resolvers import Resolver
from pex.result import Error, try_
from pex.targets import Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.util import named_temporary_file

if TYPE_CHECKING:
    from typing import Any, Dict, Iterable, Mapping, Optional, Text, Tuple, Union

_DEFAULT_BUILD_SYSTEMS = {}  # type: Dict[PipVersionValue, BuildSystem]


def _default_build_system(
    pip_version,  # type: PipVersionValue
    target,  # type: Target
    resolver,  # type: Resolver
):
    # type: (...) -> BuildSystem
    global _DEFAULT_BUILD_SYSTEMS
    build_system = _DEFAULT_BUILD_SYSTEMS.get(pip_version)
    if build_system is None:
        with TRACER.timed(
            "Building {build_backend} build_backend PEX".format(build_backend=DEFAULT_BUILD_BACKEND)
        ):
            extra_env = {}  # type: Dict[str, str]
            if pip_version is PipVersion.VENDORED:
                requires = ["setuptools", "wheel"]
                resolved = tuple(
                    Distribution.load(dist_location)
                    for dist_location in third_party.expose(requires)
                )
                extra_env.update(__PEX_UNVENDORED__="1")
            else:
                requires = [pip_version.setuptools_requirement, pip_version.wheel_requirement]
                resolved = tuple(
                    installed_distribution.fingerprinted_distribution.distribution
                    for installed_distribution in resolver.resolve_requirements(
                        requirements=requires,
                        targets=Targets.from_target(target),
                    ).installed_distributions
                )
            build_system = try_(
                BuildSystem.create(
                    interpreter=target.get_interpreter(),
                    requires=requires,
                    resolved=resolved,
                    build_backend=DEFAULT_BUILD_BACKEND,
                    backend_path=(),
                    **extra_env
                )
            )
            _DEFAULT_BUILD_SYSTEMS[pip_version] = build_system
    return build_system


def _get_build_system(
    pip_version,  # type: PipVersionValue
    target,  # type: Target
    resolver,  # type: Resolver
    project_directory,  # type: str
    extra_requirements=None,  # type: Optional[Iterable[str]]
):
    # type: (...) -> Union[BuildSystem, Error]
    custom_build_system_or_error = load_build_system(
        target, resolver, project_directory, extra_requirements=extra_requirements
    )
    if custom_build_system_or_error:
        return custom_build_system_or_error
    return _default_build_system(pip_version, target, resolver)


# Exit code 75 is EX_TEMPFAIL defined in /usr/include/sysexits.h
# this seems an appropriate signal of DNE vs execute and fail.
_HOOK_UNAVAILABLE_EXIT_CODE = 75


def is_hook_unavailable_error(error):
    # type: (Job.Error) -> bool
    return error.exitcode == _HOOK_UNAVAILABLE_EXIT_CODE


def _invoke_build_hook(
    project_directory,  # type: str
    pip_version,  # type: PipVersionValue
    target,  # type: Target
    resolver,  # type: Resolver
    hook_method,  # type: str
    hook_args=(),  # type: Iterable[Any]
    hook_extra_requirements=None,  # type: Optional[Iterable[str]]
    hook_kwargs=None,  # type: Optional[Mapping[str, Any]]
    stdout=None,  # type: Optional[int]
    stderr=None,  # type: Optional[int]
):
    # type: (...) -> Union[SpawnedJob[Any], Error]

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

    build_system_or_error = _get_build_system(
        pip_version, target, resolver, project_directory, extra_requirements=hook_extra_requirements
    )
    if isinstance(build_system_or_error, Error):
        return build_system_or_error
    build_system = build_system_or_error

    # The interfaces are spec'd here: https://peps.python.org/pep-0517
    build_backend_module, _, _ = build_system.build_backend.partition(":")
    build_backend_object = build_system.build_backend.replace(":", ".")
    with named_temporary_file(mode="r") as fp:
        args = build_system.venv_pex.execute_args(
            "-c",
            dedent(
                """\
                import json
                import sys

                import {build_backend_module}


                if not hasattr({build_backend_object}, {hook_method!r}):
                    sys.exit({hook_unavailable_exit_code})

                result = {build_backend_object}.{hook_method}(*{hook_args!r}, **{hook_kwargs!r})
                with open({result_file!r}, "w") as fp:
                    json.dump(result, fp)
                """
            ).format(
                build_backend_module=build_backend_module,
                build_backend_object=build_backend_object,
                hook_method=hook_method,
                hook_args=tuple(hook_args),
                hook_kwargs=dict(hook_kwargs) if hook_kwargs else {},
                hook_unavailable_exit_code=_HOOK_UNAVAILABLE_EXIT_CODE,
                result_file=fp.name,
            ),
        )
        process = subprocess.Popen(
            args=args,
            env=build_system.env,
            cwd=project_directory,
            stdout=stdout if stdout is not None else sys.stderr.fileno(),
            stderr=stderr if stderr is not None else sys.stderr.fileno(),
        )
        return SpawnedJob.file(
            Job(command=args, process=process),
            output_file=fp.name,
            result_func=lambda file_content: json.loads(file_content.decode("utf-8")),
        )


def build_sdist(
    project_directory,  # type: str
    dist_dir,  # type: str
    pip_version,  # type: PipVersionValue
    target,  # type: Target
    resolver,  # type: Resolver
):
    # type: (...) -> Union[Text, Error]

    extra_requirements = []
    spawned_job_or_error = _invoke_build_hook(
        project_directory,
        pip_version,
        target,
        resolver,
        hook_method="get_requires_for_build_sdist",
    )
    if isinstance(spawned_job_or_error, Error):
        return spawned_job_or_error
    try:
        extra_requirements.extend(spawned_job_or_error.await_result())
    except Job.Error as e:
        if e.exitcode != _HOOK_UNAVAILABLE_EXIT_CODE:
            return Error(
                "Failed to prepare build backend for building an sdist for local project "
                "{project_directory}: {err}\n"
                "{stderr}".format(project_directory=project_directory, err=e, stderr=e.stderr)
            )

    spawned_job_or_error = _invoke_build_hook(
        project_directory,
        pip_version,
        target,
        resolver,
        hook_method="build_sdist",
        hook_args=[dist_dir],
        hook_extra_requirements=extra_requirements,
    )
    if isinstance(spawned_job_or_error, Error):
        return spawned_job_or_error
    try:
        sdist_relpath = cast(str, spawned_job_or_error.await_result())
    except Job.Error as e:
        return Error(
            "Failed to build sdist for local project {project_directory}: {err}\n"
            "{stderr}".format(project_directory=project_directory, err=e, stderr=e.stderr)
        )
    return os.path.join(dist_dir, sdist_relpath)


def spawn_prepare_metadata(
    project_directory,  # type: str
    pip_version,  # type: PipVersionValue
    target,  # type: Target
    resolver,  # type: Resolver
):
    # type: (...) -> SpawnedJob[DistMetadata]

    extra_requirements = []
    spawned_job = try_(
        _invoke_build_hook(
            project_directory,
            pip_version,
            target,
            resolver,
            hook_method="get_requires_for_build_wheel",
        )
    )
    try:
        extra_requirements.extend(spawned_job.await_result())
    except Job.Error as e:
        if e.exitcode != _HOOK_UNAVAILABLE_EXIT_CODE:
            raise e

    build_dir = os.path.join(safe_mkdtemp(), "build")
    os.mkdir(build_dir)
    spawned_job = try_(
        _invoke_build_hook(
            project_directory,
            pip_version,
            target,
            resolver,
            hook_method="prepare_metadata_for_build_wheel",
            hook_args=[build_dir],
            hook_extra_requirements=extra_requirements,
        )
    )
    return spawned_job.map(lambda _: DistMetadata.load(build_dir))
