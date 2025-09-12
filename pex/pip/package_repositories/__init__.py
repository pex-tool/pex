# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os

from pex.common import safe_mkdtemp
from pex.exceptions import reportable_unexpected_error_msg
from pex.interpreter_implementation import InterpreterImplementation
from pex.pep_508 import MarkerEnvironment
from pex.pip.download_observer import DownloadObserver, Patch, PatchSet
from pex.resolve.package_repository import Repo, ReposConfiguration
from pex.resolve.target_system import MarkerEnv, TargetSystem, UniversalTarget
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING, cast

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

        universal_target = None  # type: Optional[UniversalTarget]
        universal_target_data = data["universal_target"]
        if universal_target_data:
            implementation = universal_target_data["implementation"]
            universal_target = UniversalTarget(
                implementation=(
                    InterpreterImplementation.for_value(implementation) if implementation else None
                ),
                requires_python=tuple(
                    SpecifierSet(requires_python)
                    for requires_python in universal_target_data["requires_python"]
                ),
                systems=tuple(
                    TargetSystem.for_value(system) for system in universal_target_data["systems"]
                ),
            )

        marker_environment = None  # type: Optional[MarkerEnvironment]
        marker_environment_data = data["marker_environment"]
        if marker_environment_data:
            marker_environment = MarkerEnvironment(**marker_environment_data)

        if not (bool(universal_target) ^ bool(marker_environment)):
            raise AssertionError(
                reportable_unexpected_error_msg(
                    "Expected exactly one of lock_configuration or marker_environment to be "
                    "defined, found data: {data}",
                    data=data,
                )
            )

        return cls(
            repos_configuration=ReposConfiguration.create(
                indexes=[Repo.from_dict(index) for index in data["indexes"]],
                find_links=[Repo.from_dict(find_links) for find_links in data["find_links"]],
            ),
            target=cast(
                "Union[UniversalTarget, MarkerEnvironment]",
                universal_target or marker_environment,
            ),
        )

    @classmethod
    def dump(
        cls,
        repos_configuration,  # type: ReposConfiguration
        extra_data,  # type: Union[UniversalTarget, MarkerEnvironment]
    ):
        # type: (...) -> Mapping[str, str]

        repos_config_file = os.path.join(safe_mkdtemp(), "repos_config.json")
        with open(repos_config_file, "w") as fp:
            json.dump(
                {
                    "indexes": [index.as_dict() for index in repos_configuration.index_repos],
                    "find_links": [
                        find_links.as_dict() for find_links in repos_configuration.find_links_repos
                    ],
                    "universal_target": (
                        {
                            "implementation": (
                                str(extra_data.implementation)
                                if extra_data.implementation
                                else None
                            ),
                            "requires_python": [
                                str(specifier_set) for specifier_set in extra_data.requires_python
                            ],
                            "systems": [str(system) for system in extra_data.systems],
                        }
                        if isinstance(extra_data, UniversalTarget)
                        else None
                    ),
                    "marker_environment": (
                        extra_data.as_dict() if isinstance(extra_data, MarkerEnvironment) else None
                    ),
                },
                fp,
            )
        return {cls._PEX_REPOS_CONFIG_FILE_ENV_VAR_NAME: repos_config_file}

    repos_configuration = attr.ib()  # type: ReposConfiguration
    target = attr.ib()  # type: Union[UniversalTarget, MarkerEnvironment]


def patch(
    repos_configuration,  # type: ReposConfiguration
    target,  # type: Union[UniversalTarget, MarkerEnvironment]
):
    # type: (...) -> Optional[DownloadObserver]

    env = (
        target.marker_env() if isinstance(target, UniversalTarget) else target.as_dict()
    )  # type: Union[MarkerEnv, Dict[str, str]]
    repos_configuration = repos_configuration.scoped(env)
    if not repos_configuration.find_links and not repos_configuration.indexes:
        return None

    patches = [
        Patch.from_code_resource(
            __name__, "link_collector.py", **PatchContext.dump(repos_configuration, target)
        )
    ]
    return DownloadObserver(analyzer=None, patch_set=PatchSet(patches=tuple(patches)))
