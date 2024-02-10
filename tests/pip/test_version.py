# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.pip.version import PipVersion


def test_latest():
    # type: () -> None

    assert PipVersion.LATEST != PipVersion.VENDORED
    assert PipVersion.LATEST >= PipVersion.v23_1
    assert (
        max(
            (version for version in PipVersion.values() if not version.hidden),
            key=lambda pv: pv.version,
        )
        is PipVersion.LATEST
    )
