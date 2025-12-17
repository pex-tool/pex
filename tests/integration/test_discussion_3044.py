# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess
from textwrap import dedent

from pex.common import environment_as
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir
from testing.scie import skip_if_no_provider


@skip_if_no_provider
def test_scie_load_dotenv(tmpdir):
    # type: (Tempdir) -> None

    with open(tmpdir.join("exe.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import os


                print("OK?:", os.environ.get("OK"))
                """
            )
        )
    pex = tmpdir.join("exe.pex")
    run_pex_command(
        args=["--scie", "eager", "--exe", fp.name, "--scie-load-dotenv", "-o", pex]
    ).assert_success()

    with environment_as(OK=None):
        assert b"OK?: None" == subprocess.check_output(args=[pex]).strip()

        scie = tmpdir.join("exe")
        assert b"OK?: None" == subprocess.check_output(args=[scie]).strip()

        with open(tmpdir.join(".env"), "w") as fp:
            fp.write("OK=42")
        assert b"OK?: None" == subprocess.check_output(args=[scie]).strip()
        assert b"OK?: None" == subprocess.check_output(args=[pex], cwd=tmpdir.path).strip()
        assert b"OK?: 42" == subprocess.check_output(args=[scie], cwd=tmpdir.path).strip()
