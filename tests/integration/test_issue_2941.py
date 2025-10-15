# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess
import sys
from typing import Text

import pytest

from pex.layout import Layout
from pex.os import LINUX, is_exe
from pex.pep_427 import InstallableType
from pex.venv.virtualenv import Virtualenv
from testing import PY_VER, make_env, run_pex_command
from testing.pep_427 import get_installable_type_flag
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(PY_VER < (3, 6), reason="The wheel under test requires Python >= 3.6")
@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
@pytest.mark.parametrize(
    "installable_type",
    [
        pytest.param(installable_type, id=installable_type.value.replace(" ", "-"))
        for installable_type in InstallableType.values()
    ],
)
def test_exotic_data_dirs_pex(
    tmpdir,  # type: Tempdir
    layout,  # type: Layout.Value
    installable_type,  # type: InstallableType.Value
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("dist", "pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--layout",
            layout.value,
            get_installable_type_flag(installable_type),
            "tritonclient==2.41.0",
            "--intransitive",
            "--include-tools",
            "-o",
            pex,
        ]
    ).assert_success()

    def get_tritonclient_import_file(pex_dir):
        # type: (str) -> Text
        return (
            subprocess.check_output(
                args=[
                    sys.executable,
                    pex_dir,
                    "-c",
                    "import tritonclient; print(tritonclient.__file__)",
                ],
                env=make_env(PEX_IGNORE_ERRORS=1),
            )
            .decode("utf-8")
            .strip()
        )

    path = get_tritonclient_import_file(pex)
    assert path.endswith(os.path.join(".prefix", "purelib", "tritonclient", "__init__.py"))

    venv_dir = tmpdir.join("venv")
    subprocess.check_call(
        args=[sys.executable, pex, "venv", venv_dir], env=make_env(PEX_TOOLS=1, PEX_IGNORE_ERRORS=1)
    )
    path = get_tritonclient_import_file(venv_dir)
    venv = Virtualenv(venv_dir)
    assert os.path.join(venv.site_packages_dir, "tritonclient", "__init__.py") == path

    perf_analyzer = venv.bin_path("perf_analyzer")
    assert is_exe(perf_analyzer) if LINUX else not os.path.exists(perf_analyzer)

    perf_client = venv.bin_path("perf_client")
    assert is_exe(perf_client) if LINUX else not os.path.exists(perf_client)
