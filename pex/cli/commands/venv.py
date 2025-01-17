# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import logging
import os.path
from argparse import ArgumentParser, _ActionsContainer

from pex import pex_warnings
from pex.cli.command import BuildTimeCommand
from pex.commands.command import JsonMixin, OutputMixin
from pex.common import DETERMINISTIC_DATETIME, CopyMode, open_zip, pluralize
from pex.dist_metadata import Distribution
from pex.enum import Enum
from pex.executables import is_script
from pex.executor import Executor
from pex.pex import PEX
from pex.pex_info import PexInfo
from pex.resolve import configured_resolve, requirement_options, resolver_options, target_options
from pex.resolve.resolver_configuration import (
    LockRepositoryConfiguration,
    PexRepositoryConfiguration,
    PipConfiguration,
)
from pex.result import Error, Ok, Result, try_
from pex.targets import LocalInterpreter, Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.venv import installer, installer_options
from pex.venv.install_scope import InstallScope
from pex.venv.installer import Provenance
from pex.venv.installer_configuration import InstallerConfiguration
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    from typing import Any, Dict, Iterable, Optional


logger = logging.getLogger(__name__)


class InstallLayout(Enum["InstallLayout.Value"]):
    class Value(Enum.Value):
        pass

    VENV = Value("venv")
    FLAT = Value("flat")
    FLAT_ZIPPED = Value("flat-zipped")


InstallLayout.seal()


class Venv(OutputMixin, JsonMixin, BuildTimeCommand):
    @classmethod
    def _add_inspect_arguments(cls, parser):
        # type: (_ActionsContainer) -> None
        parser.add_argument(
            "venv",
            help="The path of either the venv directory or its Python interpreter.",
        )
        cls.add_output_option(parser, entity="venv information")
        cls.add_json_options(parser, entity="venv information")

    @classmethod
    def _add_create_arguments(cls, parser):
        # type: (_ActionsContainer) -> None
        parser.add_argument(
            "-d",
            "--dir",
            "--dest-dir",
            dest="dest_dir",
            metavar="VENV_DIR",
            required=True,
            help=(
                "The directory to install the venv or flat layout in. If the layout is "
                "{flat_zipped}, then the directory will be installed to and then the zip created "
                "at the same path with a '.zip' extension.".format(
                    flat_zipped=InstallLayout.FLAT_ZIPPED
                )
            ),
        )
        parser.add_argument(
            "--prefix",
            dest="prefix",
            help=(
                "A prefix directory to nest the installation in under the dest dir. This is mainly "
                "useful in the {flat_zipped} layout to inject a fixed prefix to all zip "
                "entries".format(flat_zipped=InstallLayout.FLAT_ZIPPED)
            ),
        )
        parser.add_argument(
            "--layout",
            default=InstallLayout.VENV,
            choices=InstallLayout.values(),
            type=InstallLayout.for_value,
            help=(
                "The layout to create. By default, this is a standard {venv} layout including "
                "activation scripts and a hermetic `sys.path`. The {flat} and {flat_zipped} "
                "layouts can be selected when just the `sys.path` entries are desired. This"
                "effectively exports what would otherwise be the venv `site-packages` directory as "
                "a flat directory that can be joined to the `sys.path` of a compatible"
                "interpreter. These layouts are useful for runtimes that supply an isolated Python "
                "runtime already like AWS Lambda. As a technical detail, these flat layouts "
                "emulate the result of `pip install --target` and include non `site-packages` "
                "installation artifacts at the top level. The common example being a top-level "
                "`bin/` dir containing console scripts.".format(
                    venv=InstallLayout.VENV,
                    flat=InstallLayout.FLAT,
                    flat_zipped=InstallLayout.FLAT_ZIPPED,
                )
            ),
        )
        installer_options.register(parser)
        target_options.register(parser, include_platforms=True)
        resolver_options.register(
            parser, include_pex_repository=True, include_lock=True, include_pre_resolved=True
        )
        requirement_options.register(parser)

    @classmethod
    def add_extra_arguments(
        cls,
        parser,  # type: ArgumentParser
    ):
        # type: (...) -> None
        subcommands = cls.create_subcommands(
            parser,
            description="Interact with virtual environments via the following subcommands.",
        )
        with subcommands.parser(
            name="inspect",
            help="Inspect an existing venv.",
            func=cls._inspect,
            include_verbosity=False,
        ) as inspect_parser:
            cls._add_inspect_arguments(inspect_parser)
        with subcommands.parser(
            name="create",
            help="Create a venv.",
            func=cls._create,
            include_verbosity=True,
        ) as create_parser:
            cls._add_create_arguments(create_parser)

    def _inspect(self):
        # type: () -> Result

        venv = self.options.venv
        if not os.path.exists(venv):
            return Error("The given venv path of {venv} does not exist.".format(venv=venv))

        if os.path.isdir(venv):
            virtualenv = Virtualenv(os.path.normpath(venv))
            if not virtualenv.interpreter.is_venv:
                return Error("{venv} is not a venv.".format(venv=venv))
        else:
            maybe_venv = Virtualenv.enclosing(os.path.normpath(venv))
            if not maybe_venv:
                return Error("{python} is not an venv interpreter.".format(python=venv))
            virtualenv = maybe_venv

        try:
            pex = PexInfo.from_pex(virtualenv.venv_dir)
            is_pex = True
            pex_version = pex.build_properties.get("pex_version")
        except (IOError, OSError, ValueError):
            is_pex = False
            pex_version = None

        venv_info = dict(
            venv_dir=virtualenv.venv_dir,
            provenance=dict(
                created_by=virtualenv.created_by,
                is_pex=is_pex,
                pex_version=pex_version,
            ),
            include_system_site_packages=virtualenv.include_system_site_packages,
            interpreter=dict(
                binary=virtualenv.interpreter.binary,
                base_binary=virtualenv.interpreter.resolve_base_interpreter().binary,
                version=virtualenv.interpreter.identity.version_str,
                sys_path=virtualenv.sys_path,
            ),
            script_dir=virtualenv.bin_dir,
            scripts=sorted(
                os.path.relpath(exe, virtualenv.bin_dir)
                for exe in virtualenv.iter_executables()
                if is_script(exe)
            ),
            site_packages=virtualenv.site_packages_dir,
            distributions=sorted(
                str(dist.as_requirement()) for dist in virtualenv.iter_distributions()
            ),
        )  # type: Dict[str, Any]

        with self.output(self.options) as out:
            self.dump_json(self.options, venv_info, out)
            out.write("\n")

        return Ok()

    def _create(self):
        # type: () -> Result

        resolver_configuration = resolver_options.configure(self.options)
        targets = target_options.configure(
            self.options,
            pip_configuration=(
                resolver_configuration
                if isinstance(resolver_configuration, PipConfiguration)
                else resolver_configuration.pip_configuration
            ),
        ).resolve_targets()
        installer_configuration = installer_options.configure(self.options)

        dest_dir = (
            os.path.join(self.options.dest_dir, self.options.prefix)
            if self.options.prefix
            else self.options.dest_dir
        )
        update = os.path.exists(dest_dir) and not installer_configuration.force
        layout = self.options.layout

        subject = "venv" if layout is InstallLayout.VENV else "flat sys.path directory entry"

        venv = None  # type: Optional[Virtualenv]
        if update and layout is InstallLayout.VENV:
            venv = Virtualenv(venv_dir=dest_dir)
            target = LocalInterpreter.create(venv.interpreter)  # type: Target
            specified_target = try_(
                targets.require_at_most_one_target(
                    purpose="updating venv at {dest_dir}".format(dest_dir=dest_dir)
                )
            )
            if specified_target:
                if specified_target.is_foreign:
                    return Error(
                        "Cannot update a local venv using a foreign platform. Given: "
                        "{platform}.".format(platform=specified_target.platform)
                    )
                original_interpreter = venv.interpreter.resolve_base_interpreter()
                specified_interpreter = (
                    specified_target.get_interpreter().resolve_base_interpreter()
                )
                if specified_interpreter != original_interpreter:
                    return Error(
                        "Cannot update venv at {dest_dir} created with {original_python} using "
                        "{specified_python}".format(
                            dest_dir=dest_dir,
                            original_python=original_interpreter.binary,
                            specified_python=specified_interpreter.binary,
                        )
                    )
            targets = Targets.from_target(target)
        else:
            target = try_(
                targets.require_unique_target(
                    purpose="creating a {subject}".format(subject=subject)
                )
            )
            if layout is InstallLayout.VENV:
                if target.is_foreign:
                    return Error(
                        "Cannot create a local venv for foreign platform {platform}.".format(
                            platform=target.platform
                        )
                    )

                venv = Virtualenv.create(
                    venv_dir=dest_dir,
                    interpreter=target.get_interpreter(),
                    force=installer_configuration.force,
                    copies=installer_configuration.copies,
                    system_site_packages=installer_configuration.system_site_packages,
                    prompt=installer_configuration.prompt,
                )

        requirement_configuration = requirement_options.configure(self.options)
        with TRACER.timed("Resolving distributions"):
            resolved = configured_resolve.resolve(
                targets=targets,
                requirement_configuration=requirement_configuration,
                resolver_configuration=resolver_configuration,
            )

        pex = None  # type: Optional[PEX]
        lock = None  # type: Optional[str]
        if isinstance(resolver_configuration, PexRepositoryConfiguration):
            pex = PEX(resolver_configuration.pex_repository, interpreter=target.get_interpreter())
        elif isinstance(resolver_configuration, LockRepositoryConfiguration):
            lock = resolver_configuration.lock_file_path

        with TRACER.timed(
            "Installing {count} {wheels} in {subject} at {dest_dir}".format(
                count=len(resolved.distributions),
                wheels=pluralize(resolved.distributions, "wheel"),
                subject=subject,
                dest_dir=dest_dir,
            )
        ):
            hermetic_scripts = not update and installer_configuration.hermetic_scripts
            distributions = tuple(
                resolved_distribution.distribution
                for resolved_distribution in resolved.distributions
            )
            provenance = (
                Provenance.create(venv=venv)
                if venv
                else Provenance(target_dir=dest_dir, target_python=target.get_interpreter().binary)
            )
            if pex:
                _install_from_pex(
                    pex=pex,
                    installer_configuration=installer_configuration,
                    provenance=provenance,
                    distributions=distributions,
                    dest_dir=dest_dir,
                    hermetic_scripts=hermetic_scripts,
                    venv=venv,
                )
            elif venv:
                installer.populate_venv_distributions(
                    venv=venv,
                    distributions=distributions,
                    provenance=provenance,
                    copy_mode=(
                        CopyMode.COPY
                        if installer_configuration.site_packages_copies
                        else CopyMode.LINK
                    ),
                    hermetic_scripts=hermetic_scripts,
                )
            else:
                installer.populate_flat_distributions(
                    dest_dir=dest_dir,
                    distributions=distributions,
                    provenance=provenance,
                    copy_mode=(
                        CopyMode.COPY
                        if installer_configuration.site_packages_copies
                        else CopyMode.LINK
                    ),
                )
            source = (
                "PEX at {pex}".format(pex=pex.path())
                if pex
                else "lock at {lock}".format(lock=lock)
                if lock
                else "resolved requirements"
            )
            provenance.check_collisions(
                collisions_ok=installer_configuration.collisions_ok, source=source
            )

        if venv and installer_configuration.pip:
            with TRACER.timed("Installing Pip"):
                try_(
                    installer.ensure_pip_installed(
                        venv,
                        distributions=distributions,
                        scope=installer_configuration.scope,
                        collisions_ok=installer_configuration.collisions_ok,
                        source=source,
                    )
                )

        if installer_configuration.compile:
            with TRACER.timed("Compiling venv sources"):
                try:
                    target.get_interpreter().execute(["-m", "compileall", dest_dir])
                except Executor.NonZeroExit as non_zero_exit:
                    pex_warnings.warn("ignoring compile error {}".format(repr(non_zero_exit)))

        if layout is InstallLayout.FLAT_ZIPPED:
            paths = sorted(
                os.path.join(root, path)
                for root, dirs, files in os.walk(dest_dir)
                for path in itertools.chain(dirs, files)
            )
            unprefixed_dest_dir = self.options.dest_dir
            with open_zip("{dest_dir}.zip".format(dest_dir=unprefixed_dest_dir), "w") as zf:
                for path in paths:
                    zip_entry = zf.zip_entry_from_file(
                        filename=path,
                        arcname=os.path.relpath(path, unprefixed_dest_dir),
                        date_time=DETERMINISTIC_DATETIME.timetuple(),
                    )
                    zf.writestr(zip_entry.info, zip_entry.data)

        return Ok()


def _install_from_pex(
    pex,  # type: PEX
    installer_configuration,  # type: InstallerConfiguration
    provenance,  # type: Provenance
    distributions,  # type: Iterable[Distribution]
    dest_dir,  # type: str
    hermetic_scripts,  # type: bool
    venv=None,  # type: Optional[Virtualenv]
):
    # type: (...) -> None

    if installer_configuration.scope in (InstallScope.ALL, InstallScope.DEPS_ONLY):
        if venv:
            top_level_source_packages = tuple(installer.iter_top_level_source_packages(pex))
            installer.populate_venv_distributions(
                venv=venv,
                distributions=distributions,
                provenance=provenance,
                copy_mode=(
                    CopyMode.COPY if installer_configuration.site_packages_copies else CopyMode.LINK
                ),
                hermetic_scripts=hermetic_scripts,
                top_level_source_packages=top_level_source_packages,
            )
        else:
            installer.populate_flat_distributions(
                dest_dir=dest_dir,
                distributions=distributions,
                provenance=provenance,
                copy_mode=(
                    CopyMode.COPY if installer_configuration.site_packages_copies else CopyMode.LINK
                ),
            )

    if installer_configuration.scope in (InstallScope.ALL, InstallScope.SOURCE_ONLY):
        if venv:
            installer.populate_venv_sources(
                venv=venv,
                pex=pex,
                provenance=provenance,
                bin_path=installer_configuration.bin_path,
                hermetic_scripts=hermetic_scripts,
            )
        else:
            installer.populate_flat_sources(dst=dest_dir, pex=pex, provenance=provenance)
