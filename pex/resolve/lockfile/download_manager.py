# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

from pex.common import atomic_directory
from pex.resolve.locked_resolve import Artifact
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class DownloadedArtifact(object):
    path = attr.ib()  # type: str

    def fingerprint(self):
        # type: () -> str
        with open(os.path.join(os.path.dirname(self.path), "sha1"), "rb") as fp:
            return str(fp.read().decode("ascii"))


class DownloadManager(object):
    def __init__(self, pex_root=None):
        # type: (Optional[str]) -> None
        self._download_dir = os.path.join(pex_root or ENV.PEX_ROOT, "downloads")

    def store(self, artifact):
        # type: (Artifact) -> DownloadedArtifact

        download_dir = os.path.join(self._download_dir, artifact.fingerprint.hash)
        with atomic_directory(download_dir, exclusive=True) as atomic_dir:
            if not atomic_dir.is_finalized():
                dest = os.path.join(atomic_dir.work_dir, artifact.filename)
                internal_fingerprint = self.save(artifact, dest)
                with open(os.path.join(atomic_dir.work_dir, "sha1"), "wb") as fp:
                    fp.write(internal_fingerprint.encode("ascii"))

        return DownloadedArtifact(path=os.path.join(download_dir, artifact.filename))

    def save(
        self,
        artifact,  # type: Artifact
        path,  # type: str
    ):
        # type: (...) -> str
        """Save the given `artifact` at `path` and return its sha1 hex digest."""
        raise NotImplementedError()
