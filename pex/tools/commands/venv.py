# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import errno
import logging
import os
import subprocess
from argparse import ArgumentParser
from collections import OrderedDict
from subprocess import CalledProcessError
from typing import Iterable, Union

from pex import pex_warnings
from pex.common import safe_delete, safe_rmtree
from pex.dist_metadata import Distribution
from pex.enum import Enum
from pex.executor import Executor
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.result import Error, Ok, Result, try_
from pex.tools.command import PEXCommand
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.venv.bin_path import BinPath
from pex.venv.install_scope import InstallScope
from pex.venv.pex import populate_venv
from pex.venv.virtualenv import PipUnavailableError, Virtualenv

if TYPE_CHECKING:
    from typing import Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


logger = logging.getLogger(__name__)


class RemoveScope(Enum["RemoveScope.Value"]):
    class Value(Enum.Value):
        pass

    PEX = Value("pex")
    PEX_AND_PEX_ROOT = Value("all")


@attr.s(frozen=True)
class InstallScopeState(object):
    @classmethod
    def load(cls, venv_dir):
        # type: (str) -> InstallScopeState

        state_file = os.path.join(venv_dir, ".pex-venv-scope")
        prior_state = None  # type: Optional[InstallScope.Value]
        try:
            with open(state_file) as fp:
                prior_state = InstallScope.for_value(fp.read().strip())
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise e

        return cls(venv_dir=venv_dir, state_file=state_file, prior_state=prior_state)

    venv_dir = attr.ib()  # type: str
    _state_file = attr.ib()  # type: str
    _prior_state = attr.ib(default=None)  # type: Optional[InstallScope.Value]

    @property
    def is_partial_install(self):
        return self._prior_state in (InstallScope.DEPS_ONLY, InstallScope.SOURCE_ONLY)

    def save(self, install_scope):
        # type: (InstallScope.Value) -> None
        if {InstallScope.DEPS_ONLY, InstallScope.SOURCE_ONLY} == {self._prior_state, install_scope}:
            install_scope = InstallScope.ALL
        with open(self._state_file, "w") as fp:
            fp.write(str(install_scope))


def find_dist(
    project_name,  # type: ProjectName
    dists,  # type: Iterable[Distribution]
):
    # type: (...) -> Optional[Version]
    for dist in dists:
        if project_name == dist.metadata.project_name:
            return dist.metadata.version
    return None


_PIP = ProjectName("pip")
_SETUPTOOLS = ProjectName("setuptools")


def ensure_pip_installed(
    venv,  # type: Virtualenv
    pex,  # type: PEX
    scope,  # type: InstallScope.Value
    collisions_ok,  # type: bool
):
    # type: (...) -> Union[Version, Error]

    venv_pip_version = find_dist(_PIP, venv.iter_distributions())
    if venv_pip_version:
        TRACER.log(
            "The venv at {venv_dir} already has Pip {version} installed.".format(
                venv_dir=venv.venv_dir, version=venv_pip_version
            )
        )
    else:
        try:
            venv.install_pip()
        except PipUnavailableError as e:
            return Error(
                "The virtual environment was successfully created, but Pip was not "
                "installed:\n{}".format(e)
            )
        venv_pip_version = find_dist(_PIP, venv.iter_distributions())
        if not venv_pip_version:
            return Error(
                "Failed to install pip into venv at {venv_dir}".format(venv_dir=venv.venv_dir)
            )

    if InstallScope.SOURCE_ONLY == scope:
        return venv_pip_version

    uninstall = OrderedDict()
    pex_pip_version = find_dist(_PIP, pex.resolve())
    if pex_pip_version and pex_pip_version != venv_pip_version:
        uninstall[_PIP] = pex_pip_version

    venv_setuptools_version = find_dist(_SETUPTOOLS, venv.iter_distributions())
    if venv_setuptools_version:
        pex_setuptools_version = find_dist(_SETUPTOOLS, pex.resolve())
        if pex_setuptools_version and venv_setuptools_version != pex_setuptools_version:
            uninstall[_SETUPTOOLS] = pex_setuptools_version

    if not uninstall:
        return venv_pip_version

    message = (
        "You asked for --pip to be installed in the venv at {venv_dir},\n"
        "but the PEX at {pex} already contains:\n{distributions}"
    ).format(
        venv_dir=venv.venv_dir,
        pex=pex.path(),
        distributions="\n".join(
            "{project_name} {version}".format(project_name=project_name, version=version)
            for project_name, version in uninstall.items()
        ),
    )
    if not collisions_ok:
        return Error("{message}.\nConsider re-running without --pip.".format(message=message))

    pex_warnings.warn(
        "{message}.\nUninstalling venv versions and using versions from the PEX.".format(
            message=message
        )
    )
    projects_to_uninstall = sorted(str(project_name) for project_name in uninstall)
    try:
        subprocess.check_call(
            args=[venv.interpreter.binary, "-m", "pip", "uninstall", "-y"] + projects_to_uninstall
        )
    except CalledProcessError as e:
        return Error(
            "Failed to uninstall venv versions of {projects}: {err}".format(
                projects=" and ".join(projects_to_uninstall), err=e
            )
        )
    return pex_pip_version or venv_pip_version


class Venv(PEXCommand):
    """Creates a venv from the PEX file."""

    @classmethod
    def add_arguments(cls, parser):
        # type: (ArgumentParser) -> None
        parser.add_argument(
            "venv",
            nargs=1,
            metavar="PATH",
            help="The directory to create the virtual environment in.",
        )
        parser.add_argument(
            "--scope",
            default=InstallScope.ALL.value,
            choices=InstallScope.values(),
            type=InstallScope.for_value,
            help=(
                "The scope of code contained in the Pex that is installed in the venv. By default"
                "{all} code is installed and this is generally what you want. However, in some "
                "situations it's beneficial to split the venv installation into {deps} and "
                "{sources} steps. This is particularly useful when installing a PEX in a container "
                "image. See "
                "https://pex.readthedocs.io/en/latest/recipes.html#pex-app-in-a-container for more "
                "information.".format(
                    all=InstallScope.ALL,
                    deps=InstallScope.DEPS_ONLY,
                    sources=InstallScope.SOURCE_ONLY,
                )
            ),
        )
        parser.add_argument(
            "-b",
            "--bin-path",
            default=BinPath.FALSE.value,
            choices=BinPath.values(),
            type=BinPath.for_value,
            help="Add the venv bin dir to the PATH in the __main__.py script.",
        )
        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            default=False,
            help="If the venv directory already exists, overwrite it.",
        )
        parser.add_argument(
            "--collisions-ok",
            action="store_true",
            default=False,
            help=(
                "Don't error if population of the venv encounters distributions in the PEX file "
                "with colliding files, just emit a warning."
            ),
        )
        parser.add_argument(
            "-p",
            "--pip",
            action="store_true",
            default=False,
            help=(
                "Add pip (and setuptools) to the venv. If the PEX already contains its own "
                "conflicting versions pip (or setuptools), the command will error and you must "
                "pass --collisions-ok to have the PEX versions over-ride the natural venv versions "
                "installed by --pip."
            ),
        )
        parser.add_argument(
            "--copies",
            action="store_true",
            default=False,
            help="Create the venv using copies of system files instead of symlinks",
        )
        parser.add_argument(
            "--compile",
            action="store_true",
            default=False,
            help="Compile all `.py` files in the venv.",
        )
        parser.add_argument(
            "--prompt",
            help="A custom prompt for the venv activation scripts to use.",
        )
        parser.add_argument(
            "--rm",
            "--remove",
            dest="remove",
            default=None,
            choices=RemoveScope.values(),
            type=RemoveScope.for_value,
            help=(
                "Remove the PEX after creating a venv from it if the {pex!r} value is specified; "
                "otherwise, remove the PEX and the PEX_ROOT if the {all!r} value is "
                "specified.".format(
                    pex=RemoveScope.PEX.value, all=RemoveScope.PEX_AND_PEX_ROOT.value
                )
            ),
        )
        parser.add_argument(
            "--non-hermetic-scripts",
            dest="hermetic_scripts",
            action="store_false",
            default=True,
            help=(
                "Don't rewrite Python script shebangs in the venv to pass `-sE` to the "
                "interpreter; for example, to enable running the venv PEX itself or its Python "
                "scripts with a custom `PYTHONPATH`."
            ),
        )
        cls.register_global_arguments(parser, include_verbosity=False)

    def run(self, pex):
        # type: (PEX) -> Result

        venv_dir = self.options.venv[0]
        install_scope_state = InstallScopeState.load(venv_dir)
        if install_scope_state.is_partial_install and not self.options.force:
            venv = Virtualenv(venv_dir)
        else:
            venv = Virtualenv.create(
                venv_dir,
                interpreter=pex.interpreter,
                force=self.options.force,
                copies=self.options.copies,
                prompt=self.options.prompt,
            )

        if self.options.pip:
            try_(
                ensure_pip_installed(
                    venv, pex, scope=self.options.scope, collisions_ok=self.options.collisions_ok
                )
            )

        if self.options.prompt != venv.custom_prompt:
            logger.warning(
                "Unable to apply custom --prompt {prompt!r} in {python} venv; continuing with the "
                "default prompt.".format(
                    prompt=self.options.prompt, python=venv.interpreter.identity
                )
            )
        populate_venv(
            venv,
            pex,
            bin_path=self.options.bin_path,
            collisions_ok=self.options.collisions_ok,
            symlink=False,
            scope=self.options.scope,
            hermetic_scripts=self.options.hermetic_scripts,
        )

        if self.options.compile:
            try:
                pex.interpreter.execute(["-m", "compileall", venv_dir])
            except Executor.NonZeroExit as non_zero_exit:
                pex_warnings.warn("ignoring compile error {}".format(repr(non_zero_exit)))

        if self.options.remove is not None:
            if os.path.isdir(pex.path()):
                safe_rmtree(pex.path())
            else:
                safe_delete(pex.path())
            if self.options.remove is RemoveScope.PEX_AND_PEX_ROOT:
                safe_rmtree(pex.pex_info().pex_root)

        install_scope_state.save(self.options.scope)
        return Ok()
