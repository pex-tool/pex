# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import glob
import os.path
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.common import touch
from pex.typing import TYPE_CHECKING
from testing import run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 7) or sys.version_info >= (3, 13),
    reason=(
        "This test needs to run Poetry which requires at least Python 3.7. Poetry also indirectly "
        "depends on rpds-py (0.18.1 currently), which uses PyO3 which requires Python<3.13."
    ),
)
def test_wheel_file_url_dep(tmpdir):
    # type: (Any) -> None

    constraints = os.path.join(str(tmpdir), "constraints.txt")
    with open(constraints, "w") as fp:
        # The 20.22 release introduces a change that breaks resolution of poetry 1.3.2; so we pin
        # low.
        print("virtualenv<20.22", file=fp)
        # The poetry-plugin-export 1.4.0 release requires poetry>1.5 but poetry 1.3.2 floats the
        # poetry-plugin-export dep; so we pin low.
        print("poetry-plugin-export<1.4", file=fp)

    poetry = os.path.join(str(tmpdir), "poetry.pex")
    run_pex_command(
        args=["poetry==1.3.2", "--constraints", constraints, "-c", "poetry", "-o", poetry]
    ).assert_success()

    corelibrary = os.path.join(str(tmpdir), "corelibrary")
    touch(os.path.join(corelibrary, "README.md"))
    with open(os.path.join(corelibrary, "corelibrary.py"), "w") as fp:
        print("TWO = 2", file=fp)
    subprocess.check_call(args=[poetry, "init", "--no-interaction"], cwd=corelibrary)

    anotherlibrary = os.path.join(str(tmpdir), "anotherlibrary")
    touch(os.path.join(anotherlibrary, "README.md"))
    with open(os.path.join(anotherlibrary, "anotherlibrary.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from corelibrary import TWO


                MEANING_OF_LIFE = TWO * 21
                """
            )
        )
    subprocess.check_call(
        args=[poetry, "init", "--no-interaction", "--dependency", "../corelibrary"],
        cwd=anotherlibrary,
    )

    mylibrary = os.path.join(str(tmpdir), "mylibrary")
    touch(os.path.join(mylibrary, "README.md"))
    with open(os.path.join(mylibrary, "mylibrary.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from anotherlibrary import MEANING_OF_LIFE


                def deep_thought():
                    print(f"MEANING_OF_LIFE = {MEANING_OF_LIFE}")
                """
            )
        )
    subprocess.check_call(
        args=[poetry, "init", "--no-interaction", "--dependency", "../anotherlibrary"],
        cwd=mylibrary,
    )

    subprocess.check_call(args=[poetry, "build", "-f", "wheel"], cwd=mylibrary)
    wheels = glob.glob(os.path.join(mylibrary, "dist", "*.whl"))
    assert len(wheels) == 1
    wheel = wheels[0]

    pex_root = os.path.join(str(tmpdir), "pex_root")
    testing_pex = os.path.join(str(tmpdir), "testing.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--resolver-version",
            "pip-2020-resolver",
            # N.B.: Modern Pip is needed to handle Poetry relative path deps. Older Pip does
            # building off in a tmp dir and that breaks relative path references.
            "--pip-version",
            "22.3",
            wheel,
            "-e",
            "mylibrary:deep_thought",
            "-o",
            testing_pex,
        ]
    ).assert_success()
    assert (
        "MEANING_OF_LIFE = 42"
        == subprocess.check_output(args=[testing_pex]).decode("utf-8").strip()
    )
