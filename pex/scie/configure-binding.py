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


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "pex_hash",
        nargs=1,
        help="The PEX hash.",
    )
    parser.add_argument("--venv-bin-dir", help="The platform-specific venv bin dir name.")
    options = parser.parse_args()

    pex_hash = options.pex_hash[0]

    try:
        pex = find_pex_dir(pex_hash)
    except PexDirNotFound:
        sys.exit(
            "Failed to determine installed PEX (pex_hash: {pex_hash}) directory using sys.path:{eol}    {sys_path}".format(
                pex_hash=pex_hash,
                eol=os.linesep,
                sys_path=os.linesep.join("    {entry}".format(entry=entry) for entry in sys.path),
            )
        )

    write_bindings(
        env_file=os.environ["SCIE_BINDING_ENV"],
        pex=pex,
        venv_bin_dir=os.path.join(pex, options.venv_bin_dir) if options.venv_bin_dir else None,
    )
    sys.exit(0)
