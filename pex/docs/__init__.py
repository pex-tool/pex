# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional


def root(doc_type="html"):
    # type: (str) -> Optional[str]

    doc_root = os.path.join(os.path.dirname(__file__), doc_type)
    return doc_root if os.path.isdir(doc_root) else None
