# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.cache import root as cache_root
from pex.typing import TYPE_CHECKING
from testing import make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any


def test_mount_respects_env(
    pex_project_dir,  # type: str
    tmpdir,  # type: Any
):
    # type: (...) -> None

    home = os.path.join(str(tmpdir), "home")

    rel_pex_root = os.path.relpath(cache_root.path(expand_user=False), "~")
    pex_root = os.path.join(home, rel_pex_root)
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
