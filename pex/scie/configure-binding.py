# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import errno
import json
import os
import sys
from argparse import ArgumentParser

# When running under MyPy, this will be set to True for us automatically; so we can use it as a
# typing module import guard to protect Python 2 imports of typing - which is not normally available
# in Python 2.
TYPE_CHECKING = False

if TYPE_CHECKING:
    from typing import Iterable, Optional


def write_bindings(
    env_file,  # type: str
    pex,  # type: str
    venv_bin_dir=None,  # type: Optional[str]
    desktop_file=None,  # type: Optional[str]
):
    # type: (...) -> None

    with open(env_file, "a") as fp:
        print("PYTHON=" + sys.executable, file=fp)
        print("PEX=" + pex, file=fp)
        if venv_bin_dir:
            print("VIRTUAL_ENV=" + os.path.dirname(venv_bin_dir), file=fp)
            print("VENV_BIN_DIR_PLUS_SEP=" + venv_bin_dir + os.path.sep, file=fp)
        if desktop_file:
            print("DESKTOP_FILE=" + desktop_file, file=fp)


class PexDirNotFound(Exception):
    pass


def find_pex_dir(
    pex_hash,  # type: str
    search_path,  # type: Iterable[str]
):
    # type: (...) -> str

    for entry in search_path:
        pex_info = os.path.join(entry, "PEX-INFO")
        if not os.path.exists(pex_info):
            continue
        try:
            with open(pex_info) as fp:
                data = json.load(fp)
        except (IOError, OSError, ValueError):
            continue
        else:
            if pex_hash == data.get("pex_hash"):
                return os.path.realpath(entry)
    raise PexDirNotFound()


def _desktop_install_path(app_name):
    # type: (str) -> str
    return os.path.join(
        os.path.expanduser(os.environ.get("XDG_DATA_HOME", os.path.join("~", ".local", "share"))),
        "applications",
        "{app_name}.desktop".format(app_name=app_name),
    )


def desktop_install(
    app_name,  # type: str
    desktop_file,  # type: str
    desktop_install_path,  # type: str
    scie_jump,  # type: str
    scie_lift,  # type: str
    scie_exe,  # type: str
    icon=None,  # type: Optional[str]
):
    # type: (...) -> None

    try:
        os.makedirs(os.path.dirname(desktop_install_path))
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

    def maybe_quote(value):
        # type: (str) -> str
        if " " in value:
            return '"{value}"'.format(value=value)
        return value

    with open(desktop_file) as in_fp, open(desktop_install_path, "w") as out_fp:
        fmt_dict = dict(
            name=app_name,
            exe=scie_exe,
            default_exec="{scie_jump} --launch={scie_lift}".format(
                scie_jump=maybe_quote(scie_jump), scie_lift=maybe_quote(scie_lift)
            ),
        )
        if icon:
            fmt_dict.update(icon=icon)
        out_fp.write(in_fp.read().format(**fmt_dict))


class UninstallError(Exception):
    pass


def desktop_uninstall(desktop_file):
    # type: (str) -> None
    try:
        os.unlink(desktop_file)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise UninstallError(
                "Failed to uninstall {desktop_file}: {err}".format(desktop_file=desktop_file, err=e)
            )


def prompt_desktop_install(
    app_name,  # type: str
    desktop_file,  # type: str
    desktop_install_path,  # type: str
    scie_jump,  # type: str
    scie_lift,  # type: str
    scie_exe,  # type: str
    icon=None,  # type: Optional[str]
):
    # type: (...) -> None

    if sys.version_info[0] == 2:
        from Tkinter import tkMessageBox as messagebox  # type: ignore[import]
    else:
        from tkinter import messagebox as messagebox

    if messagebox.askyesno(
        title="Create Desktop Entry",
        message="Install a desktop entry?",
        detail="This will make it easier to launch {app_name}.".format(app_name=app_name),
    ):
        desktop_install(
            app_name=app_name,
            desktop_file=desktop_file,
            desktop_install_path=desktop_install_path,
            scie_jump=scie_jump,
            scie_lift=scie_lift,
            scie_exe=scie_exe,
            icon=icon,
        )


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "pex_hash",
        nargs=1,
        help="The PEX hash.",
    )
    parser.add_argument("--venv-bin-dir", help="The platform-specific venv bin dir name.")
    parser.add_argument("--desktop-file", help="An optional application .desktop file.")
    parser.add_argument("--scie-name", help="The name of the scie.")
    parser.add_argument("--scie-jump", help="The path of this scie's scie-jump tip extracted.")
    parser.add_argument("--scie-lift", help="The path of this scie's lift manifest extracted.")
    parser.add_argument("--icon", help="An optional application icon file.")
    parser.add_argument(
        "--no-prompt-desktop-install",
        dest="prompt_desktop_install",
        default=True,
        action="store_false",
        help=(
            "If a `--desktop-file` is passed, always install it without prompting unless the "
            "CONFIGURE_DESKTOP_INSTALL env var is set and directs otherwise."
        ),
    )
    options = parser.parse_args()

    pex_hash = options.pex_hash[0]

    search_path = [sys.prefix] if options.venv_bin_dir else sys.path
    try:
        pex = find_pex_dir(pex_hash, search_path)
    except PexDirNotFound:
        sys.exit(
            "Failed to determine installed PEX (pex_hash: {pex_hash}) directory using search "
            "path:\n"
            "    {search_path}".format(
                pex_hash=pex_hash,
                search_path=os.linesep.join(
                    "    {entry}".format(entry=entry) for entry in search_path
                ),
            )
        )

    desktop_install_path = None  # type: Optional[str]
    if options.desktop_file:
        desktop_install_path = _desktop_install_path(options.scie_name)
        exe = os.environ["SCIE"]
        override_install_desktop_file = os.environ.get("CONFIGURE_DESKTOP_INSTALL", "").lower()
        if override_install_desktop_file == "prompt" or (
            not override_install_desktop_file and options.prompt_desktop_install
        ):
            prompt_desktop_install(
                app_name=options.scie_name,
                desktop_file=options.desktop_file,
                desktop_install_path=desktop_install_path,
                scie_jump=options.scie_jump,
                scie_lift=options.scie_lift,
                scie_exe=exe,
                icon=options.icon,
            )
        elif override_install_desktop_file in ("1", "true") or (
            not override_install_desktop_file and not options.prompt_desktop_install
        ):
            desktop_install(
                app_name=options.scie_name,
                desktop_file=options.desktop_file,
                desktop_install_path=desktop_install_path,
                scie_jump=options.scie_jump,
                scie_lift=options.scie_lift,
                scie_exe=exe,
                icon=options.icon,
            )
        elif override_install_desktop_file == "uninstall":
            desktop_uninstall(desktop_file=desktop_install_path)

    write_bindings(
        env_file=os.environ["SCIE_BINDING_ENV"],
        pex=pex,
        venv_bin_dir=os.path.join(pex, options.venv_bin_dir) if options.venv_bin_dir else None,
        desktop_file=desktop_install_path,
    )
    sys.exit(0)
