# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

from pex.testing import make_env, run_pex_command, run_simple_pex
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_venv_mode_pex_path(tmpdir):
    # type: (Any) -> None

    test_file = os.path.join(str(tmpdir), "test.py")
    with open(test_file, "w") as fp:
        fp.write(
            dedent(
                """
                import sys

                try:
                    __import__(sys.argv[1])
                except ImportError:
                    sys.exit(int(sys.argv[2]))
                """
            )
        )

    empty_pex = os.path.join(str(tmpdir), "empty.pex")
    results = run_pex_command(args=["--venv", "-o", empty_pex])
    results.assert_success()

    output, returncode = run_simple_pex(empty_pex, args=[test_file, "colors", "37"])
    assert 37 == returncode, output.decode("utf-8")

    colors_pex = os.path.join(str(tmpdir), "colors.pex")
    results = run_pex_command(args=["ansicolors==1.1.8", "-o", colors_pex])
    results.assert_success()

    # Exporting PEX_PATH should re-create the venv.
    output, returncode = run_simple_pex(
        empty_pex, args=[test_file, "colors", "37"], env=make_env(PEX_PATH=colors_pex)
    )
    assert 0 == returncode, output.decode("utf-8")

    results = run_pex_command(args=["--pex-path", colors_pex, "--venv", "-o", empty_pex])
    results.assert_success()

    output, returncode = run_simple_pex(empty_pex, args=[test_file, "colors", "37"])
    assert 0 == returncode

    # Exporting PEX_PATH should re-create the venv, adding to --pex-path.
    pkginfo_pex = os.path.join(str(tmpdir), "pkginfo.pex")
    results = run_pex_command(args=["pkginfo==1.7.0", "-o", pkginfo_pex])
    results.assert_success()

    pex_path_env = make_env(PEX_PATH=pkginfo_pex)
    output, returncode = run_simple_pex(
        empty_pex, args=[test_file, "colors", "37"], env=pex_path_env
    )
    assert 0 == returncode
    output, returncode = run_simple_pex(
        empty_pex, args=[test_file, "pkginfo", "42"], env=pex_path_env
    )
    assert 0 == returncode

    # Exporting PEX_PATH should re-create the venv since the adjoined pex file's distribution
    # contents have changed.
    results = run_pex_command(args=["ascii-ruler==0.0.4", "-o", pkginfo_pex])
    results.assert_success()
    output, returncode = run_simple_pex(
        empty_pex, args=[test_file, "colors", "37"], env=pex_path_env
    )
    assert 0 == returncode
    output, returncode = run_simple_pex(
        empty_pex, args=[test_file, "ascii_ruler", "19"], env=pex_path_env
    )
    assert 0 == returncode
    output, returncode = run_simple_pex(
        empty_pex, args=[test_file, "pkginfo", "42"], env=pex_path_env
    )
    assert 42 == returncode
