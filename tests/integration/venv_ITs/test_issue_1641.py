# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path
import subprocess
from textwrap import dedent

import pytest

from pex.testing import PY_VER, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, List


@pytest.mark.skipif(
    PY_VER >= (3, 7),
    reason=(
        "Newer versions of pylint do not use .data/ packaging and the older 1.9.5 version of "
        "pylint requires Python <3.7"
    ),
)
@pytest.mark.parametrize(
    ["execution_mode_args"],
    [
        pytest.param([], id="zipapp"),
        # N.B.: The pylint plugin discovery system does not work with --venv symlink mode.
        pytest.param(["--venv", "--venv-site-packages-copies"], id="venv (site-packages copies)"),
    ],
)
def test_missing_data_dir_entries(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    constraints = os.path.join(str(tmpdir), "constraints")
    with open(constraints, "w") as fp:
        # N.B.: This pinned resolve is known to work with Python 2.7 through 3.6 which suits our
        # purposes for the range of tests run.
        fp.write(
            dedent(
                """\
                astroid==1.6.6
                backports.functools-lru-cache==1.6.4
                configparser==4.0.2
                enum34==1.1.10
                futures==3.3.0
                isort==4.3.21
                lazy-object-proxy==1.5.2
                mccabe==0.6.1
                singledispatch==3.7.0
                six==1.16.0
                wrapt==1.13.3
                """
            )
        )
    pex_root = os.path.join(str(tmpdir), "pex_root")
    pylint_pex = os.path.join(str(tmpdir), "pylint.pex")
    run_pex_command(
        args=[
            "pylint==1.9.5",
            "setuptools==44.1.1",
            "--constraints",
            constraints,
            "-c",
            "pylint",
            "-o",
            pylint_pex,
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
        ]
        + execution_mode_args
    ).assert_success()

    output = subprocess.check_output(args=[pylint_pex, "--version"])
    assert " 1.9.5," in output.decode("utf-8")
