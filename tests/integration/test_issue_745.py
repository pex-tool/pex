# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from textwrap import dedent

import pytest

from pex.common import safe_open, temporary_dir
from pex.testing import PY27, ensure_python_venv, make_env, run_pex_command


def test_extras_isolation():
    # type: () -> None
    # Here we ensure one of our extras, `subprocess32`, is properly isolated in the transition from
    # pex bootstrapping where it is imported by `pex.executor` to execution of user code.
    python, pip = ensure_python_venv(PY27)
    subprocess.check_call([pip, "install", "subprocess32"])
    with temporary_dir() as td:
        src_dir = os.path.join(td, "src")
        with safe_open(os.path.join(src_dir, "test_issues_745.py"), "w") as fp:
            fp.write(
                dedent(
                    """\
                    import subprocess32

                    print(subprocess32.__file__)
                    """
                )
            )

        pex_file = os.path.join(td, "test.pex")

        run_pex_command(
            [
                "--sources-directory={}".format(src_dir),
                "--entry-point=test_issues_745",
                "-o",
                pex_file,
            ],
            python=python,
        )

        # The pex runtime should scrub subprocess32 since it comes from site-packages and so we should
        # not have access to it.
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_call([python, pex_file])

        # But if the pex has a declared dependency on subprocess32 we should be able to find the
        # subprocess32 bundled into the pex.
        pex_root = os.path.realpath(os.path.join(td, "pex_root"))
        run_pex_command(
            [
                "subprocess32",
                "--sources-directory={}".format(src_dir),
                "--entry-point=test_issues_745",
                "-o",
                pex_file,
            ],
            python=python,
        )

        output = subprocess.check_output([python, pex_file], env=make_env(PEX_ROOT=pex_root))

        subprocess32_location = os.path.realpath(output.decode("utf-8").strip())
        assert subprocess32_location.startswith(pex_root)
