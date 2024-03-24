# Copyright 2014 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import re
import subprocess

from pex.typing import TYPE_CHECKING
from testing import run_pex_command

if TYPE_CHECKING:
    from typing import Any


def test_requirements_pex_wheel_type_mismatch(tmpdir):
    # type: (Any)-> None

    pre_installed_reqs_pex = os.path.join(str(tmpdir), "pre_installed_reqs.pex")
    run_pex_command(args=["cowsay==5.0", "-o", pre_installed_reqs_pex]).assert_success()

    wheel_file_reqs_pex = os.path.join(str(tmpdir), "wheel_file_reqs.pex")
    run_pex_command(
        args=["cowsay==5.0", "--no-pre-install-wheels", "-o", wheel_file_reqs_pex]
    ).assert_success()

    pex = os.path.join(str(tmpdir), "pex")

    def assert_pex():
        # type: () -> None
        assert "5.0" == subprocess.check_output(args=[pex, "--version"]).decode("utf-8").strip()

    run_pex_command(
        args=["--requirements-pex", pre_installed_reqs_pex, "-c" "cowsay", "-o", pex]
    ).assert_success()
    assert_pex()

    run_pex_command(
        args=[
            "--requirements-pex",
            wheel_file_reqs_pex,
            "--no-pre-install-wheels",
            "-c",
            "cowsay",
            "-o",
            pex,
        ]
    ).assert_success()
    assert_pex()

    run_pex_command(
        args=["--no-pre-install-wheels", "--requirements-pex", pre_installed_reqs_pex], quiet=True
    ).assert_failure(
        expected_error_re=re.escape(
            "The --no-pre-install-wheels option was selected but the --requirements-pex {reqs_pex} "
            "is built with --pre-install-wheels. Any --requirements-pex you want to merge into the "
            "main PEX must be built with --no-pre-install-wheels.".format(
                reqs_pex=pre_installed_reqs_pex
            )
        )
    )

    run_pex_command(args=["--requirements-pex", wheel_file_reqs_pex], quiet=True).assert_failure(
        expected_error_re=re.escape(
            "The --pre-install-wheels option was selected but the --requirements-pex {reqs_pex} is "
            "built with --no-pre-install-wheels. Any --requirements-pex you want to merge into the "
            "main PEX must be built with --pre-install-wheels.".format(reqs_pex=wheel_file_reqs_pex)
        )
    )
