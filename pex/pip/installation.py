# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
from textwrap import dedent

from pex import pex_warnings, third_party
from pex.atomic_directory import atomic_directory
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.pex import PEX
from pex.pex_bootstrapper import VenvPex, ensure_venv
from pex.pip.tool import Pip
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve.resolvers import Resolver
from pex.targets import LocalInterpreter, RequiresPythonError, Targets
from pex.third_party import isolated
from pex.typing import TYPE_CHECKING
from pex.util import named_temporary_file
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import Callable, Dict, Iterator, Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def _pip_venv(
    version,  # type: PipVersionValue
    iter_distribution_locations,  # type: Callable[[], Iterator[str]]
    interpreter=None,  # type: Optional[PythonInterpreter]
):
    # type: (...) -> VenvPex
    path = os.path.join(ENV.PEX_ROOT, "pip-{version}.pex".format(version=version))
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
    return ensure_venv(PEX(pip_pex_path, interpreter=pip_interpreter))


def _vendored_installation(interpreter=None):
    # type: (Optional[PythonInterpreter]) -> VenvPex

    return _pip_venv(
        version=PipVersion.VENDORED,
        iter_distribution_locations=lambda: third_party.expose(("pip", "setuptools", "wheel")),
        interpreter=interpreter,
    )


def _resolved_installation(
    version,  # type: PipVersionValue
    resolver,  # type: Resolver
    interpreter=None,  # type: Optional[PythonInterpreter]
):
    # type: (...) -> VenvPex
    if version is PipVersion.VENDORED:
        return _vendored_installation(interpreter=interpreter)

    def resolve_distribution_locations():
        for installed_distribution in resolver.resolve_requirements(
            requirements=version.requirements,
            targets=Targets(interpreters=(interpreter or PythonInterpreter.get(),)),
            pip_version=PipVersion.VENDORED,
        ).installed_distributions:
            yield installed_distribution.distribution.location

    return _pip_venv(
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
):
    # type: (...) -> PipVersionValue
    try:
        validate_targets(targets, requested_version, context)
        return requested_version
    except RequiresPythonError as e:
        remaining_versions = OrderedSet([requested_version] + list(PipVersion.values()))
        remaining_versions.discard(requested_version)
        for version in remaining_versions:
            try:
                validate_targets(targets, version, context)
                pex_warnings.warn(
                    "{err}\n" "\n" "Using Pip {version} instead.".format(err=e, version=version)
                )
                return version
            except RequiresPythonError:
                continue
    return PipVersion.v20_3_4_patched


_PIP = {}  # type: Dict[PipInstallation, Pip]


def get_pip(
    interpreter=None,
    version=PipVersion.VENDORED,  # type: PipVersionValue
    resolver=None,  # type: Optional[Resolver]
):
    # type: (...) -> Pip
    """Returns a lazily instantiated global Pip object that is safe for un-coordinated use."""
    installation = PipInstallation(
        interpreter=interpreter or PythonInterpreter.get(),
        version=version,
    )
    pip = _PIP.get(installation)
    if pip is None:
        installation.check_python_applies()
        if version is PipVersion.VENDORED:
            pip = Pip(pip_pex=_vendored_installation(interpreter=interpreter))
        else:
            if resolver is None:
                raise ValueError(
                    "A resolver is required to install {requirement}".format(
                        requirement=version.requirement
                    )
                )
            pip = Pip(
                pip_pex=_resolved_installation(
                    version=version,
                    resolver=resolver,
                    interpreter=interpreter,
                )
            )
        _PIP[installation] = pip
    return pip
