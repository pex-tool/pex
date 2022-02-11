# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.testing import make_env, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_mount_respects_env(
    pex_project_dir,  # type: str
    tmpdir,  # type: Any
):
    # type: (...) -> None

    home = os.path.join(str(tmpdir), "home")

    pex_root = os.path.join(home, ".pex")
    os.makedirs(pex_root)
    os.chmod(pex_root, 0o555)
    unwritable_pex_root_warning = "PEXWarning: PEX_ROOT is configured as {}".format(pex_root)

    pex_file = os.path.join(str(tmpdir), "pex.pex")

    result = run_pex_command(
        args=[pex_project_dir, "-o", pex_file], env=make_env(HOME=home), quiet=True
    )
    result.assert_success()

    assert unwritable_pex_root_warning in result.error

    pex_root_override = os.path.join(str(tmpdir), "pex_root_override")
    result = run_pex_command(
        args=[pex_project_dir, "-o", pex_file],
        env=make_env(HOME=home, PEX_ROOT=pex_root_override),
        quiet=True,
    )
    result.assert_success()
    assert unwritable_pex_root_warning not in result.error
