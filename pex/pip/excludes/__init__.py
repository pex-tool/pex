# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os

from pex.common import safe_mkdtemp
from pex.exclude_configuration import ExcludeConfiguration
from pex.pip.download_observer import DownloadObserver, Patch, PatchSet
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional


def patch(exclude_configuration):
    # type: (ExcludeConfiguration) -> Optional[DownloadObserver]

    if not exclude_configuration:
        return None

    patches_dir = safe_mkdtemp()
    with open(os.path.join(patches_dir, "excludes.json"), "w") as excludes_fp:
        json.dump([str(req) for req in exclude_configuration], excludes_fp)

    return DownloadObserver(
        analyzer=None,
        patch_set=PatchSet.create(
            Patch.from_code_resource(__name__, "requires.py", _PEX_EXCLUDES_FILE=excludes_fp.name)
        ),
    )
