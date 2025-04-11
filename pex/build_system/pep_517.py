# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

from pex import third_party
from pex.build_system import DEFAULT_BUILD_BACKEND, BuildSystem
from pex.build_system.pep_518 import load_build_system
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
    from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple, Union

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

    result = _get_build_system(
        target,
        resolver,
        project_directory,
        extra_requirements=hook_extra_requirements,
        pip_version=pip_version,
    )
    if isinstance(result, Error):
        return result

    return result.invoke_build_hook(
        project_directory=project_directory,
        hook_method=hook_method,
        hook_args=hook_args,
        hook_kwargs=hook_kwargs,
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


def get_requires_for_build_wheel(
    project_directory,  # type: str
    target,  # type: Target
    resolver,  # type: Resolver
    pip_version=None,  # type: Optional[PipVersionValue]
):
    # type: (...) -> Tuple[str, ...]

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
        return tuple(spawned_job.await_result())
    except Job.Error as e:
        if e.exitcode != _HOOK_UNAVAILABLE_EXIT_CODE:
            raise e
    return ()


def spawn_prepare_metadata(
    project_directory,  # type: str
    target,  # type: Target
    resolver,  # type: Resolver
    pip_version=None,  # type: Optional[PipVersionValue]
):
    # type: (...) -> SpawnedJob[DistMetadata]

    extra_requirements = get_requires_for_build_wheel(
        project_directory, target, resolver, pip_version=pip_version
    )
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
