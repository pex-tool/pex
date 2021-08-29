# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.pex_info import PexInfo
from pex.testing import run_pex_command, run_simple_pex
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Dict, Tuple


def test_venv_mode_dir_hash_includes_all_pex_info_metadata(tmpdir):
    # type: (Any) -> None

    def get_fabric_versions(pex):
        # type: (str) -> Dict[str, str]
        output, returncode = run_simple_pex(pex, args=["--version"])
        assert 0 == returncode
        return dict(
            cast("Tuple[str, str]", line.split(" ", 1))
            for line in output.decode("utf-8").splitlines()
        )

    # The only difference in these two PEX files is their entrypoint. Ensure venv execution takes
    # that into account and disambiguates the otherwise identical PEX files.

    invoke_pex = os.path.join(str(tmpdir), "invoke.pex")
    results = run_pex_command(
        args=["fabric==2.6.0", "invoke==1.5.0", "--venv", "-e", "invoke", "-o", invoke_pex],
        quiet=True,
    )
    results.assert_success()
    invoke_versions = get_fabric_versions(invoke_pex)
    assert len(invoke_versions) == 1
    invoke_version = invoke_versions["Invoke"]
    assert invoke_version == "1.5.0"

    fabric_pex = os.path.join(str(tmpdir), "fabric.pex")
    results = run_pex_command(
        args=[
            "fabric==2.6.0",
            "--venv",
            "-e",
            "fabric",
            "-o",
            fabric_pex,
            "--pex-repository",
            invoke_pex,
        ],
        quiet=True,
    )
    results.assert_success()
    fabric_versions = get_fabric_versions(fabric_pex)
    assert len(fabric_versions) >= 2
    assert invoke_version == fabric_versions["Invoke"]
    assert "2.6.0" == fabric_versions["Fabric"]

    invoke_pex_info = PexInfo.from_pex(invoke_pex)
    fabric_pex_info = PexInfo.from_pex(fabric_pex)
    assert invoke_pex_info.code_hash == fabric_pex_info.code_hash
    assert invoke_pex_info.distributions == fabric_pex_info.distributions
    assert invoke_pex_info.pex_hash != fabric_pex_info.pex_hash
