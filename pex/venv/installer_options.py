# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from argparse import Namespace, _ActionsContainer

from pex.venv.bin_path import BinPath
from pex.venv.install_scope import InstallScope
from pex.venv.installer_configuration import InstallerConfiguration


def register(
    parser,  # type: _ActionsContainer
    include_force_switch=False,  # type: bool
):
    # type: (...) -> None
    default_configuration = InstallerConfiguration()
    parser.add_argument(
        "--scope",
        default=default_configuration.scope,
        choices=InstallScope.values(),
        type=InstallScope.for_value,
        help=(
            "The scope of code contained in the Pex that is installed in the venv. By default"
            "{all} code is installed and this is generally what you want. However, in some "
            "situations it's beneficial to split the venv installation into {deps} and "
            "{sources} steps. This is particularly useful when installing a PEX in a container "
            "image. See "
            "https://docs.pex-tool.org/recipes.html#pex-app-in-a-container for more "
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
        default=default_configuration.bin_path,
        choices=BinPath.values(),
        type=BinPath.for_value,
        help="Add the venv bin dir to the PATH in the __main__.py script.",
    )
    force_flags = ["-f", "--force"] if include_force_switch else ["--force"]
    parser.add_argument(
        *force_flags,
        action="store_true",
        default=False,
        help="If the venv directory already exists, overwrite it."
    )
    parser.add_argument(
        "--collisions-ok",
        action="store_true",
        default=False,
        help=(
            "Don't error if population of the ven-v encounters distributions in the PEX file "
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
        help="Create the venv using copies of system files instead of symlinks.",
    )
    parser.add_argument(
        "--site-packages-copies",
        action="store_true",
        default=False,
        help="Create the venv using copies of distributions instead of links or symlinks.",
    )
    parser.add_argument(
        "--system-site-packages",
        action="store_true",
        default=False,
        help="Give the venv access to the system site-packages dir.",
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


def configure(options):
    # type: (Namespace) -> InstallerConfiguration
    return InstallerConfiguration(
        scope=options.scope,
        bin_path=options.bin_path,
        force=options.force,
        collisions_ok=options.collisions_ok,
        pip=options.pip,
        copies=options.copies,
        site_packages_copies=options.site_packages_copies,
        system_site_packages=options.system_site_packages,
        compile=options.compile,
        prompt=options.prompt,
        hermetic_scripts=options.hermetic_scripts,
    )
