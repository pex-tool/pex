# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os
import subprocess
from textwrap import dedent

from pex import third_party
from pex.build_system import DEFAULT_BUILD_BACKEND
from pex.build_system.pep_518 import BuildSystem, load_build_system
from pex.common import safe_mkdtemp
from pex.dist_metadata import DistMetadata, Distribution, MetadataType
from pex.jobs import Job, SpawnedJob
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve.resolvers import Resolver
from pex.result import Error, try_
from pex.targets import Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Union

_DEFAULT_BUILD_SYSTEMS = {}  # type: Dict[PipVersionValue, BuildSystem]


def _default_build_system(
    target,  # type: Target
    resolver,  # type: Resolver
    pip_version=None,  # type: Optional[PipVersionValue]
):
    # type: (...) -> BuildSystem
    global _DEFAULT_BUILD_SYSTEMS
    selected_pip_version = pip_version or PipVersion.DEFAULT
    build_system = _DEFAULT_BUILD_SYSTEMS.get(selected_pip_version)
    if build_system is None:
        with TRACER.timed(
            "Building {build_backend} build_backend PEX".format(build_backend=DEFAULT_BUILD_BACKEND)
        ):
            extra_env = {}  # type: Dict[str, str]
            resolved_reqs = set()  # type: Set[str]
            resolved_dists = []  # type: List[Distribution]
            if selected_pip_version is PipVersion.VENDORED:
                requires = ["setuptools", str(selected_pip_version.wheel_requirement)]
                resolved_dists.extend(
                    Distribution.load(dist_location)
                    for dist_location in third_party.expose_installed_wheels(
                        ["setuptools"], interpreter=target.get_interpreter()
                    )
                )
                resolved_reqs.add("setuptools")
                extra_env.update(__PEX_UNVENDORED__="setuptools")
            else:
                requires = [
                    str(selected_pip_version.setuptools_requirement),
                    str(selected_pip_version.wheel_requirement),
                ]
            unresolved = [
                requirement for requirement in requires if requirement not in resolved_reqs
            ]
            resolved_dists.extend(
                resolved_distribution.fingerprinted_distribution.distribution
                for resolved_distribution in resolver.resolve_requirements(
                    requirements=unresolved,
                    targets=Targets.from_target(target),
                ).distributions
            )
            build_system = try_(
                BuildSystem.create(
                    interpreter=target.get_interpreter(),
                    requires=requires,
                    resolved=resolved_dists,
                    build_backend=DEFAULT_BUILD_BACKEND,
                    backend_path=(),
                    use_system_time=resolver.use_system_time(),
                    **extra_env
                )
            )
            _DEFAULT_BUILD_SYSTEMS[selected_pip_version] = build_system
    return build_system


def _get_build_system(
    target,  # type: Target
    resolver,  # type: Resolver
    project_directory,  # type: str
    extra_requirements=None,  # type: Optional[Iterable[str]]
    pip_version=None,  # type: Optional[PipVersionValue]
):
    # type: (...) -> Union[BuildSystem, Error]
    custom_build_system_or_error = load_build_system(
        target, resolver, project_directory, extra_requirements=extra_requirements
    )
    if custom_build_system_or_error:
        return custom_build_system_or_error
    return _default_build_system(target, resolver, pip_version=pip_version)


# Exit code 75 is EX_TEMPFAIL defined in /usr/include/sysexits.h
# this seems an appropriate signal of DNE vs execute and fail.
_HOOK_UNAVAILABLE_EXIT_CODE = 75


def is_hook_unavailable_error(error):
    # type: (Job.Error) -> bool
    return error.exitcode == _HOOK_UNAVAILABLE_EXIT_CODE


def _invoke_build_hook(
    project_directory,  # type: str
    target,  # type: Target
    resolver,  # type: Resolver
    hook_method,  # type: str
    hook_args=(),  # type: Iterable[Any]
    hook_extra_requirements=None,  # type: Optional[Iterable[str]]
    hook_kwargs=None,  # type: Optional[Mapping[str, Any]]
    pip_version=None,  # type: Optional[PipVersionValue]
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
        target,
        resolver,
        project_directory,
        extra_requirements=hook_extra_requirements,
        pip_version=pip_version,
    )
    if isinstance(build_system_or_error, Error):
        return build_system_or_error
    build_system = build_system_or_error

    # The interfaces are spec'd here: https://peps.python.org/pep-0517
    build_backend_module, _, _ = build_system.build_backend.partition(":")
    build_backend_object = build_system.build_backend.replace(":", ".")
    build_hook_result = os.path.join(safe_mkdtemp(prefix="pex-pep-517."), "build_hook_result.json")
    args = build_system.venv_pex.execute_args(
        additional_args=(
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
                result_file=build_hook_result,
            ),
        )
    )
    process = subprocess.Popen(
        args=args,
        env=build_system.env,
        cwd=project_directory,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return SpawnedJob.file(
        Job(
            command=args,
            process=process,
            context="PEP-517:{hook_method} at {project_directory}".format(
                hook_method=hook_method, project_directory=project_directory
            ),
        ),
        output_file=build_hook_result,
        result_func=lambda file_content: json.loads(file_content.decode("utf-8")),
    )


def build_sdist(
    project_directory,  # type: str
    dist_dir,  # type: str
    target,  # type: Target
    resolver,  # type: Resolver
    pip_version=None,  # type: Optional[PipVersionValue]
):
    # type: (...) -> Union[str, Error]

    extra_requirements = []
    spawned_job_or_error = _invoke_build_hook(
        project_directory,
        target,
        resolver,
        hook_method="get_requires_for_build_sdist",
        pip_version=pip_version,
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
        target,
        resolver,
        hook_method="build_sdist",
        hook_args=[dist_dir],
        hook_extra_requirements=extra_requirements,
        pip_version=pip_version,
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
    target,  # type: Target
    resolver,  # type: Resolver
    pip_version=None,  # type: Optional[PipVersionValue]
):
    # type: (...) -> SpawnedJob[DistMetadata]

    extra_requirements = []
    spawned_job = try_(
        _invoke_build_hook(
            project_directory,
            target,
            resolver,
            hook_method="get_requires_for_build_wheel",
            pip_version=pip_version,
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
            target,
            resolver,
            hook_method="prepare_metadata_for_build_wheel",
            hook_args=[build_dir],
            hook_extra_requirements=extra_requirements,
            pip_version=pip_version,
        )
    )
    return spawned_job.map(lambda _: DistMetadata.load(build_dir, MetadataType.DIST_INFO))
