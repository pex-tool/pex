# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import hashlib
import os
from collections import OrderedDict
from textwrap import dedent

from pex import pep_427, pex_warnings, third_party
from pex.atomic_directory import atomic_directory
from pex.cache.dirs import InstalledWheelDir, PipPexDir
from pex.common import REPRODUCIBLE_BUILDS_ENV, CopyMode, pluralize, safe_mkdtemp
from pex.dist_metadata import Requirement
from pex.exceptions import production_assert
from pex.executor import Executor
from pex.interpreter import PythonInterpreter
from pex.jobs import iter_map_parallel
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.pex_bootstrapper import ensure_venv
from pex.pip.tool import Pip, PipVenv
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve.resolvers import Resolver
from pex.result import Error, try_
from pex.targets import LocalInterpreter, RequiresPythonError, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper
from pex.variables import ENV, Variables
from pex.venv.virtualenv import InstallationChoice, Virtualenv

if TYPE_CHECKING:
    from typing import Callable, Dict, Iterator, Optional, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def _create_pip(
    pip_pex,  # type: PipPexDir
    interpreter=None,  # type: Optional[PythonInterpreter]
    use_system_time=False,  # type: bool
    record_access=True,  # type: bool
):
    # type: (...) -> Pip

    production_assert(os.path.exists(pip_pex.path))

    pip_interpreter = interpreter or PythonInterpreter.get()
    pex = PEX(pip_pex.path, interpreter=pip_interpreter)
    venv_pex = ensure_venv(pex, copy_mode=CopyMode.SYMLINK, record_access=record_access)
    pex_hash = pex.pex_info().pex_hash
    production_assert(pex_hash is not None)
    pip_venv = PipVenv(
        venv_dir=venv_pex.venv_dir,
        pex_hash=cast(str, pex_hash),
        execute_env=tuple(REPRODUCIBLE_BUILDS_ENV.items()) if not use_system_time else (),
        execute_args=tuple(venv_pex.execute_args()),
    )
    return Pip(pip_pex=pip_pex, pip_venv=pip_venv)


def _pip_installation(
    version,  # type: PipVersionValue
    iter_distribution_locations,  # type: Callable[[], Iterator[str]]
    fingerprint,  # type: str
    interpreter=None,  # type: Optional[PythonInterpreter]
    use_system_time=False,  # type: bool
):
    # type: (...) -> Pip

    pip_pex = PipPexDir.create(version, fingerprint)
    with atomic_directory(pip_pex.path) as chroot:
        if not chroot.is_finalized():
            from pex.pex_builder import PEXBuilder

            isolated_pip_builder = PEXBuilder(path=chroot.work_dir, copy_mode=CopyMode.SYMLINK)
            isolated_pip_builder.info.venv = True
            # Allow REPRODUCIBLE_BUILDS_ENV PYTHONHASHSEED env var to take effect if needed.
            isolated_pip_builder.info.venv_hermetic_scripts = False
            for dist_location in iter_distribution_locations():
                isolated_pip_builder.add_dist_location(dist=dist_location)
            with open(os.path.join(chroot.work_dir, "__pex_patched_pip__.py"), "w") as fp:
                fp.write(
                    dedent(
                        """\
                        import os
                        import runpy

                        patches_package = os.environ.pop({patches_package_env_var_name!r}, None)
                        if patches_package:
                            # Apply runtime patches to Pip to work around issues or else bend
                            # Pip to Pex's needs.
                            __import__(patches_package)

                        runpy.run_module(mod_name="pip", run_name="__main__", alter_sys=True)
                        """
                    ).format(patches_package_env_var_name=Pip._PATCHES_PACKAGE_ENV_VAR_NAME)
                )
            isolated_pip_builder.set_executable(fp.name, "exe.py")
            isolated_pip_builder.freeze()
    return _create_pip(pip_pex, interpreter=interpreter, use_system_time=use_system_time)


def _fingerprint(requirements):
    # type: (Tuple[Requirement, ...]) -> str
    if not requirements:
        return "no-extra-requirements"
    return hashlib.sha1("\n".join(sorted(map(str, requirements))).encode("utf-8")).hexdigest()


_PIP_PROJECT_NAME = ProjectName("pip")
_SETUPTOOLS_PROJECT_NAME = ProjectName("setuptools")
_WHEEL_PROJECT_NAME = ProjectName("wheel")


def _vendored_installation(
    interpreter=None,  # type: Optional[PythonInterpreter]
    resolver=None,  # type: Optional[Resolver]
    extra_requirements=(),  # type: Tuple[Requirement, ...]
    use_system_time=False,  # type: bool
):
    # type: (...) -> Pip

    def expose_vendored():
        # type: () -> Iterator[str]
        return third_party.expose_installed_wheels(("pip", "setuptools"), interpreter=interpreter)

    if not extra_requirements:
        return _pip_installation(
            version=PipVersion.VENDORED,
            iter_distribution_locations=expose_vendored,
            interpreter=interpreter,
            fingerprint=_fingerprint(extra_requirements),
            use_system_time=use_system_time,
        )

    if not resolver:
        raise ValueError(
            "A resolver is required to install extra {requirements} for vendored Pip: "
            "{extra_requirements}".format(
                requirements=pluralize(extra_requirements, "requirement"),
                extra_requirements=" ".join(map(str, extra_requirements)),
            )
        )

    # Ensure user-specified extra requirements do not override vendored Pip or its setuptools and
    # wheel dependencies. These are arranged just so with some patching to Pip and setuptools as
    # well as a low enough standard wheel version to support Python 2.7.
    for extra_req in extra_requirements:
        if _PIP_PROJECT_NAME == extra_req.project_name:
            raise ValueError(
                "An `--extra-pip-requirement` cannot be used to override the Pip version; use "
                "`--pip-version` to select a supported Pip version instead. "
                "Given: {pip_req}".format(pip_req=extra_req)
            )
        if _SETUPTOOLS_PROJECT_NAME == extra_req.project_name:
            raise ValueError(
                "An `--extra-pip-requirement` cannot be used to override the setuptools version "
                "for vendored Pip. If you need a custom setuptools you need to use `--pip-version` "
                "to select a non-vendored Pip version. Given: {setuptools_req}".format(
                    setuptools_req=extra_req
                )
            )
        if _WHEEL_PROJECT_NAME == extra_req.project_name:
            raise ValueError(
                "An `--extra-pip-requirement` cannot be used to override the wheel version for "
                "vendored Pip. If you need a custom wheel version you need to use `--pip-version` "
                "to select a non-vendored Pip version. Given: {wheel_req}".format(
                    wheel_req=extra_req
                )
            )

    # This indirection works around MyPy type inference failing to see that
    # `iter_distribution_locations` is only successfully defined when resolve is not None.
    extra_requirement_resolver = resolver

    def iter_distribution_locations():
        # type: () -> Iterator[str]
        for location in expose_vendored():
            yield location

        for resolved_distribution in extra_requirement_resolver.resolve_requirements(
            requirements=tuple(map(str, extra_requirements)),
            targets=Targets.from_target(LocalInterpreter.create(interpreter)),
            pip_version=PipVersion.VENDORED,
            extra_resolver_requirements=(),
        ).distributions:
            yield resolved_distribution.distribution.location

    return _pip_installation(
        version=PipVersion.VENDORED,
        iter_distribution_locations=iter_distribution_locations,
        interpreter=interpreter,
        fingerprint=_fingerprint(extra_requirements),
        use_system_time=use_system_time,
    )


class PipInstallError(Exception):
    """Indicates an error installing Pip."""


def _install_wheel(wheel_path):
    # type: (str) -> str

    # TODO(John Sirois): Consolidate with pex.resolver.BuildAndInstallRequest.
    #  https://github.com/pex-tool/pex/issues/2556
    wheel_hash = CacheHelper.hash(wheel_path, hasher=hashlib.sha256)
    wheel_name = os.path.basename(wheel_path)
    installed_wheel_dir = InstalledWheelDir.create(wheel_name=wheel_name, install_hash=wheel_hash)
    with atomic_directory(installed_wheel_dir) as atomic_dir:
        if not atomic_dir.is_finalized():
            installed_wheel = pep_427.install_wheel_chroot(
                wheel_path=wheel_path, destination=atomic_dir.work_dir
            )
            runtime_key_dir = InstalledWheelDir.create(
                wheel_name=wheel_name,
                install_hash=(
                    installed_wheel.fingerprint
                    or CacheHelper.dir_hash(atomic_dir.work_dir, hasher=hashlib.sha256)
                ),
                wheel_hash=wheel_hash,
            )
            production_assert(runtime_key_dir.symlink_dir is not None)
            with atomic_directory(cast(str, runtime_key_dir.symlink_dir)) as runtime_atomic_dir:
                if not runtime_atomic_dir.is_finalized():
                    source_path = os.path.join(runtime_atomic_dir.work_dir, wheel_name)
                    relative_target_path = os.path.relpath(
                        installed_wheel_dir, runtime_key_dir.symlink_dir
                    )
                    os.symlink(relative_target_path, source_path)
    return installed_wheel_dir


def _bootstrap_pip(
    version,  # type: PipVersionValue
    interpreter=None,  # type: Optional[PythonInterpreter]
):
    # type: (...) -> Callable[[], Iterator[str]]

    def bootstrap_pip():
        # type: () -> Iterator[str]

        chroot = safe_mkdtemp()
        venv = Virtualenv.create(
            venv_dir=os.path.join(chroot, "pip"),
            interpreter=interpreter,
            install_pip=InstallationChoice.YES,
        )

        wheels = os.path.join(chroot, "wheels")
        wheels_cmd = ["-m", "pip", "wheel", "--wheel-dir", wheels]
        wheels_cmd.extend(str(req) for req in version.requirements)
        try:
            venv.interpreter.execute(args=wheels_cmd)
        except Executor.NonZeroExit as e:
            raise PipInstallError(
                "Failed to bootstrap Pip {version}.\n"
                "Failed to download its dependencies: {err}".format(version=version, err=str(e))
            )

        return iter_map_parallel(
            inputs=glob.glob(os.path.join(wheels, "*.whl")),
            function=_install_wheel,
            costing_function=os.path.getsize,
            noun="wheel",
            verb="install",
            verb_past="installed",
        )

    return bootstrap_pip


def _resolved_installation(
    version,  # type: PipVersionValue
    resolver=None,  # type: Optional[Resolver]
    interpreter=None,  # type: Optional[PythonInterpreter]
    extra_requirements=(),  # type: Tuple[Requirement, ...]
    use_system_time=False,  # type: bool
):
    # type: (...) -> Pip
    targets = Targets.from_target(LocalInterpreter.create(interpreter))

    bootstrap_pip_version = try_(
        compatible_version(
            targets,
            PipVersion.VENDORED,
            context="Bootstrapping Pip {version}".format(version=version),
            warn=False,
        )
    )
    if bootstrap_pip_version is not PipVersion.VENDORED and not extra_requirements:
        return _pip_installation(
            version=version,
            iter_distribution_locations=_bootstrap_pip(version, interpreter=interpreter),
            interpreter=interpreter,
            fingerprint=_fingerprint(extra_requirements),
            use_system_time=use_system_time,
        )

    requirements_by_project_name = OrderedDict(
        (req.project_name, str(req)) for req in version.requirements
    )

    # Allow user-specified extra requirements to override Pip requirements (setuptools and wheel).
    for extra_req in extra_requirements:
        if _PIP_PROJECT_NAME == extra_req.project_name:
            raise ValueError(
                "An `--extra-pip-requirement` cannot be used to override the Pip version; use "
                "`--pip-version` to select a supported Pip version instead. "
                "Given: {pip_req}".format(pip_req=extra_req)
            )
        existing_req = requirements_by_project_name.get(extra_req.project_name)
        if existing_req:
            TRACER.log(
                "Overriding `--pip-version {pip_version}` requirement of {existing_req} with "
                "user-specified requirement {extra_req}".format(
                    pip_version=version.version, existing_req=existing_req, extra_req=extra_req
                )
            )
        requirements_by_project_name[extra_req.project_name] = str(extra_req)

    if not resolver:
        raise ValueError(
            "A resolver is required to install {requirements} for Pip {version}: {reqs}".format(
                requirements=pluralize(requirements_by_project_name, "requirement"),
                version=version,
                reqs=" ".join(requirements_by_project_name.values()),
            )
        )

    def resolve_distribution_locations():
        for resolved_distribution in resolver.resolve_requirements(
            requirements=requirements_by_project_name.values(),
            targets=targets,
            pip_version=bootstrap_pip_version,
            extra_resolver_requirements=(),
        ).distributions:
            yield resolved_distribution.distribution.location

    return _pip_installation(
        version=version,
        iter_distribution_locations=resolve_distribution_locations,
        interpreter=interpreter,
        fingerprint=_fingerprint(extra_requirements),
        use_system_time=use_system_time,
    )


@attr.s(frozen=True)
class PipInstallation(object):
    interpreter = attr.ib()  # type: PythonInterpreter
    version = attr.ib()  # type: PipVersionValue
    extra_requirements = attr.ib()  # type: Tuple[Requirement, ...]
    use_system_time = attr.ib()  # type: bool

    # We use this to isolate installations by PEX_ROOT for tests. In production, there will only
    # ever be 1 PEX_ROOT per Pex process lifetime.
    pex_root = attr.ib(init=False)  # type: str

    def __attrs_post_init__(self):
        object.__setattr__(self, "pex_root", ENV.PEX_ROOT)

    def check_python_applies(self):
        # type: () -> None
        if not self.version.requires_python_applies(LocalInterpreter.create(self.interpreter)):
            raise RequiresPythonError(
                "The Pip requested was {pip_requirement} but it does not work with the interpreter "
                "selected which is {python_impl} {python_version} at {python_binary}. Pip "
                "{pip_version} requires Python {requires_python}.".format(
                    pip_requirement=self.version.requirement,
                    pip_version=self.version.value,
                    python_impl=self.interpreter.identity.interpreter,
                    python_version=self.interpreter.identity.version_str,
                    python_binary=self.interpreter.binary,
                    requires_python=self.version.requires_python,
                )
            )


def validate_targets(
    targets,  # type: Targets
    version,  # type: PipVersionValue
    context,  # type: str
):
    # type: (...) -> None
    all_targets = targets.unique_targets()
    invalid_targets = [
        target for target in all_targets if not version.requires_python_applies(target)
    ]
    if invalid_targets:
        raise RequiresPythonError(
            "The Pip requested for {context} was {pip_requirement} but it does not work with "
            "{quantifier} targets selected.\n"
            "\n"
            "Pip {pip_version} requires Python {requires_python} and the following {targets_do} "
            "not apply:\n"
            "{invalid_targets}"
            "".format(
                context=context,
                pip_requirement=version.requirement,
                quantifier="any of the"
                if len(invalid_targets) == len(all_targets)
                else "{invalid} out of the {total}".format(
                    invalid=len(invalid_targets), total=len(all_targets)
                ),
                pip_version=version.value,
                requires_python=version.requires_python,
                targets_do="target does" if len(invalid_targets) == 1 else "targets do",
                invalid_targets="\n".join(
                    "{index}. {target}".format(index=index, target=target)
                    for index, target in enumerate(invalid_targets, start=1)
                ),
            )
        )


def compatible_version(
    targets,  # type: Targets
    requested_version,  # type: PipVersionValue
    context,  # type: str
    warn=True,  # type: bool
):
    # type: (...) -> Union[PipVersionValue, Error]
    try:
        validate_targets(targets, requested_version, context)
        return requested_version
    except RequiresPythonError as e:
        remaining_versions = OrderedSet([requested_version] + list(PipVersion.values()))
        remaining_versions.discard(requested_version)
        for version in remaining_versions:
            try:
                validate_targets(targets, version, context)
                if warn:
                    pex_warnings.warn(
                        "{err}\n" "\n" "Using Pip {version} instead.".format(err=e, version=version)
                    )
                return version
            except RequiresPythonError:
                continue
    return Error(
        "No supported version of Pip is compatible with the given targets:\n{targets}".format(
            targets="\n".join(
                sorted(target.render_description() for target in targets.unique_targets())
            )
        )
    )


_PIP = {}  # type: Dict[PipInstallation, Pip]


def get_pip(
    interpreter=None,
    version=None,  # type: Optional[PipVersionValue]
    resolver=None,  # type: Optional[Resolver]
    extra_requirements=(),  # type: Tuple[Requirement, ...]
):
    # type: (...) -> Pip
    """Returns a lazily instantiated global Pip object that is safe for un-coordinated use."""
    if version:
        calculated_version = version
    elif PipVersion.DEFAULT is PipVersion.VENDORED:
        calculated_version = PipVersion.VENDORED
    else:
        # If no explicit Pip version was requested, and we're using Python 3.12+, the new semantic
        # is to allow selecting the appropriate Pip for the interpreter at hand without warning.
        # This is required since Python 3.12+ do not work with the vendored Pip.
        target = LocalInterpreter.create(interpreter)
        calculated_version = try_(
            compatible_version(
                targets=Targets.from_target(target),
                requested_version=PipVersion.DEFAULT,
                context="Selecting Pip for {target}".format(target=target.render_description()),
            )
        )

    installation = PipInstallation(
        interpreter=interpreter or PythonInterpreter.get(),
        version=calculated_version,
        extra_requirements=extra_requirements,
        use_system_time=resolver.use_system_time() if resolver else False,
    )
    pip = _PIP.get(installation)
    if pip is None:
        installation.check_python_applies()
        if installation.version is PipVersion.VENDORED:
            pip = _vendored_installation(
                interpreter=interpreter,
                resolver=resolver,
                extra_requirements=installation.extra_requirements,
                use_system_time=installation.use_system_time,
            )
        else:
            pip = _resolved_installation(
                version=installation.version,
                resolver=resolver,
                interpreter=interpreter,
                extra_requirements=installation.extra_requirements,
                use_system_time=installation.use_system_time,
            )
        _PIP[installation] = pip
    return pip


def iter_all(
    interpreter=None,  # type: Optional[PythonInterpreter]
    use_system_time=False,  # type: bool
    pex_root=ENV,  # type: Union[str, Variables]
    record_access=True,  # type: bool
):
    # type: (...) -> Iterator[Pip]

    for pip_pex in PipPexDir.iter_all(pex_root=pex_root):
        yield _create_pip(
            pip_pex,
            interpreter=interpreter,
            use_system_time=use_system_time,
            record_access=record_access,
        )
