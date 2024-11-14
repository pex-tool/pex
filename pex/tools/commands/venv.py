# Copyright 2020 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import errno
import logging
import os
from argparse import ArgumentParser

from pex import pex_warnings
from pex.common import CopyMode, safe_delete, safe_rmtree
from pex.enum import Enum
from pex.executor import Executor
from pex.pex import PEX
from pex.result import Ok, Result, try_
from pex.tools.command import PEXCommand
from pex.typing import TYPE_CHECKING
from pex.venv import installer, installer_options
from pex.venv.install_scope import InstallScope
from pex.venv.virtualenv import Virtualenv

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


RemoveScope.seal()


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
        installer_options.register(parser, include_force_switch=True)
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
        cls.register_global_arguments(parser, include_verbosity=False)

    def run(self, pex):
        # type: (PEX) -> Result

        installer_configuration = installer_options.configure(self.options)

        venv_dir = self.options.venv[0]
        install_scope_state = InstallScopeState.load(venv_dir)
        if install_scope_state.is_partial_install and not installer_configuration.force:
            venv = Virtualenv(venv_dir)
        else:
            venv = Virtualenv.create(
                venv_dir,
                interpreter=pex.interpreter,
                force=installer_configuration.force,
                copies=installer_configuration.copies,
                system_site_packages=installer_configuration.system_site_packages,
                prompt=installer_configuration.prompt,
            )

        if installer_configuration.pip:
            try_(
                installer.ensure_pip_installed(
                    venv,
                    distributions=tuple(pex.resolve()),
                    scope=installer_configuration.scope,
                    collisions_ok=installer_configuration.collisions_ok,
                    source="PEX at {pex}".format(pex=pex.path()),
                )
            )

        if installer_configuration.prompt != venv.custom_prompt:
            logger.warning(
                "Unable to apply custom --prompt {prompt!r} in {python} venv; continuing with the "
                "default prompt.".format(
                    prompt=installer_configuration.prompt, python=venv.interpreter.identity
                )
            )
        installer.populate_venv_from_pex(
            venv,
            pex,
            bin_path=installer_configuration.bin_path,
            collisions_ok=installer_configuration.collisions_ok,
            copy_mode=(
                CopyMode.COPY if installer_configuration.site_packages_copies else CopyMode.LINK
            ),
            scope=installer_configuration.scope,
            hermetic_scripts=installer_configuration.hermetic_scripts,
        )

        if installer_configuration.compile:
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

        install_scope_state.save(installer_configuration.scope)
        return Ok()
