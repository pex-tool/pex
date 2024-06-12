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
    from typing import Mapping, Optional


class PatchContext(object):
    _PEX_EXCLUDES_FILE_ENV_VAR_NAME = "_PEX_EXCLUDES_FILE"

    @classmethod
    def load_exclude_configuration(cls):
        # type: () -> ExcludeConfiguration

        excludes_file = os.environ.pop(cls._PEX_EXCLUDES_FILE_ENV_VAR_NAME)
        with open(excludes_file) as fp:
            return ExcludeConfiguration.create(json.load(fp))

    @classmethod
    def dump_exclude_configuration(cls, exclude_configuration):
        # type: (ExcludeConfiguration) -> Mapping[str, str]

        patches_file = os.path.join(safe_mkdtemp(), "excludes.json")
        with open(patches_file, "w") as excludes_fp:
            json.dump([str(req) for req in exclude_configuration], excludes_fp)
        return {cls._PEX_EXCLUDES_FILE_ENV_VAR_NAME: patches_file}


def patch(exclude_configuration):
    # type: (ExcludeConfiguration) -> Optional[DownloadObserver]

    if not exclude_configuration:
        return None

    return DownloadObserver(
        analyzer=None,
        patch_set=PatchSet.create(
            Patch.from_code_resource(
                __name__,
                "requires.py",
                **PatchContext.dump_exclude_configuration(exclude_configuration)
            )
        ),
    )
