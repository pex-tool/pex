# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest

from pex.common import temporary_dir
from testing import IS_ARM_64, PY38, ensure_python_interpreter, run_pex_command


@pytest.mark.skipif(
    IS_ARM_64,
    reason=(
        "Pandas 1.0.5 requires Cython<3 to build from source, but its build_requires does not "
        "constrain an upper bound and Cython 3 was released in the intervening time."
    ),
)
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
