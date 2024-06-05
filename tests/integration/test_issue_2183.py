# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.compatibility import commonpath
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from testing import PY_VER, make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    PY_VER < (3, 7) or PY_VER >= (3, 12),
    reason=(
        "The test requires use of attrs 23.1.0 which requires Python >= 3.7 and Lambdex further "
        "requires a released version of Pex that supports Python 3.12."
    ),
)
def test_lambdex_with_incompatible_attrs(tmpdir):
    # type: (Any) -> None

    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "example.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import sys

                from attr import AttrsInstance

                def run():
                    print(sys.modules[AttrsInstance.__module__].__file__)
                """
            )
        )

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(args=["-D", src, "attrs==23.1.0", "-o", pex]).assert_success()

    pex_distributions_by_project_name = {
        dist.metadata.project_name: dist for dist in PEX(pex).resolve()
    }
    user_attrs = pex_distributions_by_project_name[ProjectName("attrs")]
    assert Version("23.1.0") == user_attrs.metadata.version

    lambda_zip = os.path.join(str(tmpdir), "lambda.zip")
    run_pex_command(
        args=[
            # The Lambdex 0.2.0 final release changed from a top-level pex.third_party import to a
            # lazy one which foils scrubbing under Python<3.8. Instead of releasing a Lambdex 0.2.1
            # with a fix for this eagerly, we just pin this test dep low to avoid the issue and see
            # if any bug report ever comes in, which seems unlikely since Python 3.7 is EOL and
            # Lambdex is as well.
            "lambdex<0.2.0",
            "-c",
            "lambdex",
            "--",
            "build",
            "-e",
            "example:run",
            "-o",
            lambda_zip,
            pex,
        ]
    ).assert_success()

    venv_dir = os.path.join(str(tmpdir), "venv_dir")
    venv = Virtualenv.create(venv_dir=venv_dir)
    output = (
        subprocess.check_output(
            args=[venv.interpreter.binary, "-c", "from lambdex_handler import handler; handler()"],
            env=make_env(PYTHONPATH=lambda_zip),
        )
        .decode("utf-8")
        .strip()
    )
    assert user_attrs.location == commonpath((user_attrs.location, output)), output
