# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.testing import PY38, ensure_python_interpreter, run_pex_command


def test_resolve_python_requires_full_version():
    # type: () -> None
    python38 = ensure_python_interpreter(PY38)
    result = run_pex_command(
        python=python38,
        args=[
            "pandas==1.0.5",
            "--",
            "-c",
            "import pandas; print(pandas._version.get_versions()['version'])",
        ],
        quiet=True,
    )
    result.assert_success()
    assert "1.0.5" == result.output.strip()
