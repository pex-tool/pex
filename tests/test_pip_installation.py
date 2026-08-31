# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import warnings

from pex.cache_check import Check
from pex.pex_warnings import PEXWarning
from pex.pip.installation import _install_wheel
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from testing import built_wheel

if TYPE_CHECKING:
    from typing import Dict

    from testing.pytest_utils.tmp import Tempdir


def snapshot_dir(directory):
    # type: (str) -> Dict[str, bytes]
    """Capture the full contents of `directory` so mutation of any kind can be detected."""

    contents = {}  # type: Dict[str, bytes]
    for root, _, files in os.walk(directory):
        for f in files:
            path = os.path.join(root, f)
            with open(path, "rb") as fp:
                contents[os.path.relpath(path, directory)] = fp.read()
    return contents


def test_install_wheel_rebuilds_around_corrupted_cache_entry(tmpdir):
    # type: (Tempdir) -> None
    """A corrupted `installed_wheels` cache entry is detected and rebuilt around under `--check`.

    This exercises `pex.pip.installation._install_wheel` directly: the code path used to install
    Pip itself (and its own build/tool dependencies like `setuptools`, `build_backend.pex`,
    `twine.pex`) via the *locked* `atomic_directory`, which is the same locked, cross-process
    populate pattern vulnerable to a stale, partially-cleaned work dir being reused.
    """
    pex_root = os.path.join(str(tmpdir.path), "pex_root")
    with ENV.patch(PEX_ROOT=pex_root), built_wheel(name="project") as wheel_path:
        install_dir1 = _install_wheel(wheel_path)
        assert os.path.isdir(install_dir1)

        record_files = [
            os.path.join(root, f)
            for root, _, files in os.walk(install_dir1)
            for f in files
            if f == "RECORD"
        ]
        assert 1 == len(record_files)
        os.unlink(record_files[0])
        before = snapshot_dir(install_dir1)

        with warnings.catch_warnings(record=True) as events:
            warnings.simplefilter("always")
            install_dir2 = _install_wheel(wheel_path, check=Check.WARN)

        assert (
            install_dir1 != install_dir2
        ), "Expected a rebuilt location outside the corrupted cache entry."
        assert os.path.isfile(
            os.path.join(install_dir2, "project-0.0.0.dist-info", "RECORD")
        )
        assert any(
            issubclass(event.category, PEXWarning)
            and "does not match the fingerprint" in str(event.message)
            for event in events
        ), "Expected a warning about the corrupted installed wheel chroot."

        # The heart of it: the shared cache entry itself must never be touched by the rebuild.
        assert before == snapshot_dir(install_dir1), "Expected the cache entry to be left untouched."

        # And `Check.NONE` (the default) must not even notice the corruption.
        install_dir3 = _install_wheel(wheel_path)
        assert install_dir1 == install_dir3
