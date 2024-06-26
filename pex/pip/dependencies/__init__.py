# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os

from pex.common import safe_mkdtemp
from pex.dependency_configuration import DependencyConfiguration
from pex.pip.download_observer import DownloadObserver, Patch, PatchSet
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Mapping, Optional


class PatchContext(object):
    _PEX_DEP_CONFIG_FILE_ENV_VAR_NAME = "_PEX_DEP_CONFIG_FILE"

    @classmethod
    def load_dependency_configuration(cls):
        # type: () -> DependencyConfiguration

        dep_config_file = os.environ.pop(cls._PEX_DEP_CONFIG_FILE_ENV_VAR_NAME)
        with open(dep_config_file) as fp:
            data = json.load(fp)
        return DependencyConfiguration.create(
            excluded=data["excluded"], overridden=data["overridden"]
        )

    @classmethod
    def dump_dependency_configuration(cls, dependency_configuration):
        # type: (DependencyConfiguration) -> Mapping[str, str]

        dep_config_file = os.path.join(safe_mkdtemp(), "dep_config.json")
        with open(dep_config_file, "w") as fp:
            json.dump(
                {
                    "excluded": [str(exclude) for exclude in dependency_configuration.excluded],
                    "overridden": [
                        str(override) for override in dependency_configuration.all_overrides()
                    ],
                },
                fp,
            )
        return {cls._PEX_DEP_CONFIG_FILE_ENV_VAR_NAME: dep_config_file}


def patch(dependency_configuration):
    # type: (DependencyConfiguration) -> Optional[DownloadObserver]

    if not dependency_configuration:
        return None

    return DownloadObserver(
        analyzer=None,
        patch_set=PatchSet.create(
            Patch.from_code_resource(
                __name__,
                "requires.py",
                **PatchContext.dump_dependency_configuration(dependency_configuration)
            )
        ),
    )
