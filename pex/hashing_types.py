# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Protocol

    class Digest(Protocol):
        def update(self, data):
            # type: (bytes) -> None
            pass

    class HintedDigest(Digest, Protocol):
        @property
        def block_size(self):
            # type: () -> int
            pass

    class Hasher(HintedDigest, Protocol):
        @property
        def name(self):
            # type: () -> str
            pass

        def digest(self):
            # type: () -> bytes
            pass

        def hexdigest(self):
            # type: () -> str
            pass
