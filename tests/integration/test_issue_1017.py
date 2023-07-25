# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.common import temporary_dir
from testing import PY38, ensure_python_interpreter, run_pex_command


def test_resolve_python_requires_full_version():
    # type: () -> None
    python38 = ensure_python_interpreter(PY38)
    with temporary_dir() as tmpdir:
        constraints_file = os.path.join(tmpdir, "constraints.txt")
        with open(constraints_file, "w") as fp:
            # pandas 1.0.5 has an open-ended requirement on numpy, but is in practice
            # incompatible with numpy>=1.24.0 because it drops np.bool support.
            fp.write("numpy==1.23.5")
        result = run_pex_command(
            python=python38,
            args=[
                "pandas==1.0.5",
                "--constraints",
                constraints_file,
                "--",
                "-c",
                "import pandas; print(pandas._version.get_versions()['version'])",
            ],
            quiet=True,
        )
    result.assert_success()
    assert "1.0.5" == result.output.strip()
