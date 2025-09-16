# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os

from pex.common import safe_mkdtemp
from pex.pep_508 import MarkerEnvironment
from pex.pip.download_observer import DownloadObserver, Patch, PatchSet
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve.package_repository import PackageRepositories, ReposConfiguration
from pex.resolve.target_system import MarkerEnv, UniversalTarget
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, Mapping, Optional, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class PatchContext(object):
    _PEX_REPOS_CONFIG_FILE_ENV_VAR_NAME = "_PEX_REPOS_CONFIG_FILE"

    @classmethod
    def load(cls):
        # type: () -> PatchContext

        dep_config_file = os.environ.pop(cls._PEX_REPOS_CONFIG_FILE_ENV_VAR_NAME)
        with open(dep_config_file) as fp:
            data = json.load(fp)
        return cls(
            pip_version=PipVersion.for_value(data["pip_version"]),
            package_repositories=PackageRepositories.from_dict(data["package_repositories"]),
        )

    def dump(self):
        # type: () -> Mapping[str, str]

        repos_config_file = os.path.join(safe_mkdtemp(), "repos_config.json")
        with open(repos_config_file, "w") as fp:
            json.dump(
                {
                    "pip_version": str(self.pip_version),
                    "package_repositories": self.package_repositories.as_dict(),
                },
                fp,
            )
        return {self._PEX_REPOS_CONFIG_FILE_ENV_VAR_NAME: repos_config_file}

    pip_version = attr.ib()  # type: PipVersionValue
    package_repositories = attr.ib()  # type: PackageRepositories


def patch(
    repos_configuration,  # type: ReposConfiguration
    pip_version,  # type: PipVersionValue
    target,  # type: Union[UniversalTarget, MarkerEnvironment]
):
    # type: (...) -> Optional[DownloadObserver]

    target_env = (
        target.marker_env() if isinstance(target, UniversalTarget) else target.as_dict()
    )  # type: Union[MarkerEnv, Dict[str, str]]
    package_repositories = repos_configuration.scoped(target_env)
    if not package_repositories.has_scoped_repositories:
        return None

    patches = [
        Patch.from_code_resource(
            __name__, "link_collector.py", **PatchContext(pip_version, package_repositories).dump()
        )
    ]
    return DownloadObserver(analyzer=None, patch_set=PatchSet(patches=tuple(patches)))
