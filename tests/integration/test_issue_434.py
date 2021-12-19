# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.common import temporary_dir
from pex.testing import PY310, ensure_python_interpreter, run_pex_command, run_simple_pex


def test_entry_point_targeting():
    # type: () -> None
    """Test bugfix for https://github.com/pantsbuild/pex/issues/434."""
    with temporary_dir() as td:
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            pex_python = ensure_python_interpreter(PY310)
            pexrc.write("PEX_PYTHON=%s" % pex_python)

        # test pex with entry point
        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(
            ["--disable-cache", "autopep8==1.5.6", "-e", "autopep8", "-o", pex_out_path]
        )
        res.assert_success()

        stdout, rc = run_simple_pex(pex_out_path)
        assert "usage: autopep8".encode() in stdout
