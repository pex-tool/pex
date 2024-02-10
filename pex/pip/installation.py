# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
from textwrap import dedent

from pex import pex_warnings, third_party
from pex.atomic_directory import atomic_directory
from pex.common import safe_mkdtemp
from pex.dist_metadata import Requirement
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.pex import PEX
from pex.pex_bootstrapper import ensure_venv
from pex.pip.tool import Pip, PipVenv
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve.resolvers import Resolver
from pex.result import Error, try_
from pex.targets import LocalInterpreter, RequiresPythonError, Targets
from pex.third_party import isolated
from pex.typing import TYPE_CHECKING
from pex.util import named_temporary_file
from pex.variables import ENV
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    from typing import Callable, Dict, Iterator, Optional, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def _pip_installation(
    version,  # type: PipVersionValue
    iter_distribution_locations,  # type: Callable[[], Iterator[str]]
    interpreter=None,  # type: Optional[PythonInterpreter]
):
    # type: (...) -> Pip
    pip_root = os.path.join(ENV.PEX_ROOT, "pip", str(version))
    path = os.path.join(pip_root, "pip.pex")
    pip_interpreter = interpreter or PythonInterpreter.get()
    pip_pex_path = os.path.join(path, isolated().pex_hash)
    with atomic_directory(pip_pex_path) as chroot:
        if not chroot.is_finalized():
            from pex.pex_builder import PEXBuilder

            isolated_pip_builder = PEXBuilder(path=chroot.work_dir)
            isolated_pip_builder.info.venv = True
            for dist_location in iter_distribution_locations():
                isolated_pip_builder.add_dist_location(dist=dist_location)
            with named_temporary_file(prefix="", suffix=".py", mode="w") as fp:
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
                fp.close()
                isolated_pip_builder.set_executable(fp.name, "__pex_patched_pip__.py")
            isolated_pip_builder.freeze()
    pip_cache = os.path.join(pip_root, "pip_cache")
    pip_pex = ensure_venv(PEX(pip_pex_path, interpreter=pip_interpreter))
    pip_venv = PipVenv(venv_dir=pip_pex.venv_dir, execute_args=tuple(pip_pex.execute_args()))
    return Pip(pip=pip_venv, version=version, pip_cache=pip_cache)


def _vendored_installation(interpreter=None):
    # type: (Optional[PythonInterpreter]) -> Pip

    return _pip_installation(
        version=PipVersion.VENDORED,
        iter_distribution_locations=lambda: third_party.expose(
            ("pip", "setuptools"), interpreter=interpreter
        ),
        interpreter=interpreter,
    )


def _bootstrap_pip(
    version,  # type: PipVersionValue
    interpreter=None,  # type: Optional[PythonInterpreter]
):
    # type: (...) -> Callable[[], Iterator[str]]

    def bootstrap_pip():
        # type: () -> Iterator[str]

        chroot = safe_mkdtemp()
        venv = Virtualenv.create(venv_dir=os.path.join(chroot, "pip"), interpreter=interpreter)
        venv.install_pip(upgrade=True)

        for req in version.requirements:
            project_name = Requirement.parse(req).name
            target_dir = os.path.join(chroot, "reqs", project_name)
            venv.interpreter.execute(["-m", "pip", "install", "--target", target_dir, req])
            yield target_dir

    return bootstrap_pip


def _resolved_installation(
    version,  # type: PipVersionValue
    resolver=None,  # type: Optional[Resolver]
    interpreter=None,  # type: Optional[PythonInterpreter]
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
    if bootstrap_pip_version is not PipVersion.VENDORED:
        return _pip_installation(
            version=version,
            iter_distribution_locations=_bootstrap_pip(version, interpreter=interpreter),
            interpreter=interpreter,
        )

    if resolver is None:
        raise ValueError(
            "A resolver is required to install {requirement}".format(
                requirement=version.requirement
            )
        )

    def resolve_distribution_locations():
        for resolved_distribution in resolver.resolve_requirements(
            requirements=version.requirements,
            targets=targets,
            pip_version=PipVersion.VENDORED,
        ).distributions:
            yield resolved_distribution.distribution.location

    return _pip_installation(
        version=version,
        iter_distribution_locations=resolve_distribution_locations,
        interpreter=interpreter,
    )


@attr.s(frozen=True)
class PipInstallation(object):
    interpreter = attr.ib()  # type: PythonInterpreter
    version = attr.ib()  # type: PipVersionValue

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
    )
    pip = _PIP.get(installation)
    if pip is None:
        installation.check_python_applies()
        if installation.version is PipVersion.VENDORED:
            pip = _vendored_installation(interpreter=interpreter)
        else:
            pip = _resolved_installation(
                version=installation.version, resolver=resolver, interpreter=interpreter
            )
        _PIP[installation] = pip
    return pip
