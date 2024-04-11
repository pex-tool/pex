# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import re
import subprocess
import sys

import pytest

from pex.layout import Layout
from pex.typing import TYPE_CHECKING
from testing import run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.parametrize(
    "reqs_pex_layout", [pytest.param(layout, id=str(layout)) for layout in Layout.values()]
)
@pytest.mark.parametrize(
    "out_pex_layout", [pytest.param(layout, id=str(layout)) for layout in Layout.values()]
)
def test_requirements_pex_wheel_type_mismatch(
    tmpdir,  # type: Any
    reqs_pex_layout,  # type: Layout.Value
    out_pex_layout,  # type: Layout.Value
):
    # type: (...) -> None

    pre_installed_reqs_pex = os.path.join(str(tmpdir), "pre_installed_reqs.pex")
    run_pex_command(
        args=["cowsay==5.0", "--layout", str(reqs_pex_layout), "-o", pre_installed_reqs_pex]
    ).assert_success()

    wheel_file_reqs_pex = os.path.join(str(tmpdir), "wheel_file_reqs.pex")
    run_pex_command(
        args=[
            "cowsay==5.0",
            "--no-pre-install-wheels",
            "--layout",
            str(reqs_pex_layout),
            "-o",
            wheel_file_reqs_pex,
        ]
    ).assert_success()

    pex = os.path.join(str(tmpdir), "pex")

    def assert_pex():
        # type: () -> None
        assert (
            "5.0"
            == subprocess.check_output(args=[sys.executable, pex, "--version"])
            .decode("utf-8")
            .strip()
        )

    run_pex_command(
        args=[
            "--requirements-pex",
            pre_installed_reqs_pex,
            "-c" "cowsay",
            "--layout",
            str(out_pex_layout),
            "-o",
            pex,
        ]
    ).assert_success()
    assert_pex()

    run_pex_command(
        args=[
            "--requirements-pex",
            wheel_file_reqs_pex,
            "--no-pre-install-wheels",
            "-c",
            "cowsay",
            "--layout",
            str(out_pex_layout),
            "-o",
            pex,
        ]
    ).assert_success()
    assert_pex()

    # N.B.: We cannot currently re-materialize wheel files from pre-installed wheel chroots.
    # See: https://github.com/pex-tool/pex/issues/2299
    run_pex_command(
        args=["--no-pre-install-wheels", "--requirements-pex", pre_installed_reqs_pex], quiet=True
    ).assert_failure(
        expected_error_re=re.escape(
            "Cannot resolve .whl files from PEX at {reqs_pex}; its dependencies are in the form of "
            "pre-installed wheel chroots.".format(reqs_pex=pre_installed_reqs_pex)
        )
    )

    # But we can go the other way around and turn wheel files into pre-installed wheel chroots.
    run_pex_command(args=["--requirements-pex", wheel_file_reqs_pex], quiet=True).assert_success()
