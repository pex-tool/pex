# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import json
import os
import sys
from argparse import ArgumentParser

# When running under MyPy, this will be set to True for us automatically; so we can use it as a
# typing module import guard to protect Python 2 imports of typing - which is not normally available
# in Python 2.
TYPE_CHECKING = False

if TYPE_CHECKING:
    from typing import Optional


def write_bindings(
    env_file,  # type: str
    pex,  # type: str
    venv_bin_dir=None,  # type: Optional[str]
):
    # type: (...) -> None

    with open(env_file, "a") as fp:
        print("PYTHON=" + sys.executable, file=fp)
        print("PEX=" + pex, file=fp)
        if venv_bin_dir:
            print("VIRTUAL_ENV=" + os.path.dirname(venv_bin_dir), file=fp)
            print("VENV_BIN_DIR_PLUS_SEP=" + venv_bin_dir + os.path.sep, file=fp)


class PexDirNotFound(Exception):
    pass


def find_pex_dir(pex_hash):
    # type: (str) -> str

    for entry in sys.path:
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


def prompt_install(
    desktop_file,  # type: str
    icon=None,  # type: Optional[str]
):
    # type: (...) -> None

    if sys.version_info[0] == 2:
        from Tkinter import tkMessageBox as messagebox  # type: ignore[import]
    else:
        from tkinter import messagebox as messagebox

    scie_name = os.path.basename(os.environ["SCIE_ARGV0"])
    if not messagebox.askyesno(
        title="Create Desktop Entry",
        message="Install a desktop entry?",
        detail="This will make it easier to launch {app_name}.".format(app_name=scie_name),
    ):
        return

    scie_path = os.environ["SCIE"]
    xdg_data_home = os.environ.get("XDG_DATA_HOME", os.path.join("~", ".local", "share"))
    with open(desktop_file) as in_fp, open(
        os.path.expanduser(
            os.path.join(
                xdg_data_home, "applications", "{app_name}.desktop".format(app_name=scie_name)
            )
        ),
        "w",
    ) as out_fp:
        fmt_dict = dict(name=scie_name, exe=scie_path)
        if icon:
            fmt_dict.update(icon=icon)
        out_fp.write(in_fp.read().format(**fmt_dict))


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "pex_hash",
        nargs=1,
        help="The PEX hash.",
    )
    parser.add_argument("--venv-bin-dir", help="The platform-specific venv bin dir name.")
    parser.add_argument("--desktop-file", help="An optional application .desktop file.")
    parser.add_argument("--icon", help="An optional application icon file.")
    options = parser.parse_args()

    pex_hash = options.pex_hash[0]

    try:
        pex = find_pex_dir(pex_hash)
    except PexDirNotFound:
        sys.exit(
            "Failed to determine installed PEX (pex_hash: {pex_hash}) directory using sys.path:\n"
            "    {sys_path}".format(
                pex_hash=pex_hash,
                sys_path=os.linesep.join("    {entry}".format(entry=entry) for entry in sys.path),
            )
        )

    if options.desktop_file:
        prompt_install(desktop_file=options.desktop_file, icon=options.icon)

    write_bindings(
        env_file=os.environ["SCIE_BINDING_ENV"],
        pex=pex,
        venv_bin_dir=os.path.join(pex, options.venv_bin_dir) if options.venv_bin_dir else None,
    )
    sys.exit(0)
