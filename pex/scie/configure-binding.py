# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

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
    venv_dir=None,  # type: Optional[str]
):
    # type: (...) -> None

    with open(env_file, "a") as fp:
        print("PYTHON=" + sys.executable, file=fp)
        print("PEX=" + pex, file=fp)
        if venv_dir:
            print("VENV_BIN_DIR_PLUS_SEP=" + os.path.join(venv_dir, "bin") + os.path.sep, file=fp)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--installed-pex-dir",
        help=(
            "The final resting install directory of the PEX if it is a zipapp PEX. If left unset, "
            "this indicates the PEX is a venv PEX whose resting venv directory should be "
            "determined dynamically."
        ),
    )
    options = parser.parse_args()

    if options.installed_pex_dir:
        pex = os.path.realpath(options.installed_pex_dir)
        venv_dir = None
    else:
        venv_dir = os.path.realpath(
            # N.B.: In practice, VIRTUAL_ENV should always be set by the PEX venv __main__.py
            # script.
            os.environ.get("VIRTUAL_ENV", os.path.dirname(os.path.dirname(sys.executable)))
        )
        pex = venv_dir

    write_bindings(
        env_file=os.environ["SCIE_BINDING_ENV"],
        pex=pex,
        venv_dir=venv_dir,
    )
    sys.exit(0)
