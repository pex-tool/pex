# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import glob
import os.path
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.common import touch
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 7),
    reason="This test needs to run Poetry which requires at least Python 3.7",
)
def test_wheel_file_url_dep(tmpdir):
    # type: (Any) -> None

    poetry = os.path.join(str(tmpdir), "poetry.pex")
    run_pex_command(args=["poetry==1.3.2", "-c", "poetry", "-o", poetry]).assert_success()

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
