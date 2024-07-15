# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import os
import sys


def write_bindings(
    env_file,  # type: str
    installed_pex_dir,  # type: str
):
    # type: (...) -> None
    with open(env_file, "a") as fp:
        print("PYTHON=" + sys.executable, file=fp)
        print("PEX=" + os.path.realpath(os.path.join(installed_pex_dir, "__main__.py")), file=fp)


if __name__ == "__main__":
    write_bindings(
        env_file=os.environ["SCIE_BINDING_ENV"],
        installed_pex_dir=(
            # The zipapp case:
            os.environ["_PEX_SCIE_INSTALLED_PEX_DIR"]
            # The --venv case:
            or os.environ.get("VIRTUAL_ENV", os.path.dirname(os.path.dirname(sys.executable)))
        ),
    )
    sys.exit(0)
