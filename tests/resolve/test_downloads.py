# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from contextlib import contextmanager

from pex.fs.lock import FileLockStyle
from pex.resolve import downloads
from pex.resolve.downloads import ArtifactDownloader
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Iterator


def test_fingerprint_download_uses_bsd_lock(tmpdir, monkeypatch):
    # type: (Any, Any) -> None

    artifact = tmpdir.join("artifact.whl")
    with open(artifact, "wb") as fp:
        fp.write(b"content")
    lock_styles = []

    @contextmanager
    def observe_atomic_directory(_target_dir, lock_style=None):
        # type: (str, Any) -> Iterator[Any]
        lock_styles.append(lock_style)

        class Finalized(object):
            @staticmethod
            def is_finalized():
                # type: () -> bool
                return True

        yield Finalized()

    monkeypatch.setattr(downloads, "atomic_directory", observe_atomic_directory)

    ArtifactDownloader._fingerprint_and_move(artifact)
    assert [FileLockStyle.BSD] == lock_styles
