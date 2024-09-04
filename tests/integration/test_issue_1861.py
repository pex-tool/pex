# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.cache.dirs import CacheDir
from pex.typing import TYPE_CHECKING
from testing import make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any


def test_confounding_site_packages_directory(tmpdir):
    # type: (Any) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")
    local_app_data = os.path.join(str(tmpdir), "local_app_data")
    result = run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "python-certifi-win32==1.6.1",
            "--",
            "-c",
            "import certifi_win32; print(certifi_win32.__file__)",
        ],
        # N.B.: certifi_win32 requires `LOCALAPPDATA` be set in the env to import at all.
        env=make_env(LOCALAPPDATA=local_app_data),
    )
    result.assert_success()
    assert result.output.startswith(CacheDir.INSTALLED_WHEELS.path(pex_root=pex_root))
