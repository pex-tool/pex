# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import subprocess
from textwrap import dedent

import pytest

from pex.compatibility import safe_commonpath
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir
from testing.scie import skip_if_no_provider

if TYPE_CHECKING:
    from typing import List


@pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--sh-boot"], id="SH_BOOT"),
        pytest.param(["--venv"], id="VENV"),
        pytest.param(["--venv", "--sh-boot"], id="VENV-SH_BOOT"),
    ],
)
@skip_if_no_provider
def test_use_pex_scie_as_interpreter(
    pex_wheel,  # type: str
    tmpdir,  # type: Tempdir
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex = tmpdir.join("pex")
    run_pex_command(args=[pex_wheel, "--scie", "eager", "--scie-only", "-o", pex]).assert_success()

    app = tmpdir.join("test")
    pex_root = tmpdir.join("pex_root")

    set_pex_root = tmpdir.join("set_pex_root.py")
    with open(set_pex_root, "w") as fp:
        fp.write(
            dedent(
                """\
                import os


                os.environ["PEX_ROOT"] = {pex_root!r}
                """
            ).format(pex_root=pex_root)
        )

    subprocess.check_call(
        args=[
            pex,
            "-m",
            "pex",
            "--preamble-file",
            set_pex_root,
            "--scie",
            "eager",
            "--python",
            pex,
            "--venv",
            "--prefer-wheel",
            "setproctitle",
            "pip",
            "-o",
            app,
        ]
    )

    data = json.loads(
        subprocess.check_output(
            args=[
                app,
                "-c",
                dedent(
                    """\
                    import json
                    import sys

                    import pip
                    import setproctitle


                    json.dump(
                        {"setproctitle": setproctitle.__file__, "pip": pip.__file__},
                        sys.stdout
                    )
                    """
                ),
            ]
        )
    )
    assert pex_root == safe_commonpath((pex_root, data.pop("pip")))
    assert pex_root == safe_commonpath((pex_root, data.pop("setproctitle")))
    assert not data
