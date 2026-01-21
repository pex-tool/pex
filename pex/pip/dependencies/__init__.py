# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os

from pex.common import safe_mkdtemp
from pex.dependency_configuration import DependencyConfiguration
from pex.exceptions import reportable_unexpected_error_msg
from pex.interpreter_implementation import InterpreterImplementation
from pex.pep_508 import MarkerEnvironment
from pex.pip.download_observer import DownloadObserver, Patch, PatchSet
from pex.resolve.target_system import TargetSystem, UniversalTarget
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Mapping, Optional, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class PatchContext(object):
    _PEX_DEP_CONFIG_FILE_ENV_VAR_NAME = "_PEX_DEP_CONFIG_FILE"

    @classmethod
    def load(cls):
        # type: () -> PatchContext

        dep_config_file = os.environ.pop(cls._PEX_DEP_CONFIG_FILE_ENV_VAR_NAME)
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
            dependency_configuration=DependencyConfiguration.create(
                excluded=data["excluded"], overridden=data["overridden"]
            ),
            target=cast(
                "Union[UniversalTarget, MarkerEnvironment]",
                universal_target or marker_environment,
            ),
        )

    @classmethod
    def dump(
        cls,
        dependency_configuration,  # type: DependencyConfiguration
        target,  # type: Union[UniversalTarget, MarkerEnvironment]
    ):
        # type: (...) -> Mapping[str, str]

        dep_config_file = os.path.join(safe_mkdtemp(), "dep_config.json")
        with open(dep_config_file, "w") as fp:
            json.dump(
                {
                    "excluded": [str(exclude) for exclude in dependency_configuration.excluded],
                    "overridden": [
                        str(override) for override in dependency_configuration.all_overrides()
                    ],
                    "universal_target": (
                        {
                            "implementation": (
                                str(target.implementation) if target.implementation else None
                            ),
                            "requires_python": [
                                str(specifier_set) for specifier_set in target.requires_python
                            ],
                            "systems": [str(system) for system in target.systems],
                        }
                        if isinstance(target, UniversalTarget)
                        else None
                    ),
                    "marker_environment": (
                        target.as_dict() if isinstance(target, MarkerEnvironment) else None
                    ),
                },
                fp,
            )
        return {cls._PEX_DEP_CONFIG_FILE_ENV_VAR_NAME: dep_config_file}

    dependency_configuration = attr.ib()  # type: DependencyConfiguration
    target = attr.ib()  # type: Union[UniversalTarget, MarkerEnvironment]


def patch(
    dependency_configuration,  # type: DependencyConfiguration
    target,  # type: Union[UniversalTarget, MarkerEnvironment]
):
    # type: (...) -> Optional[DownloadObserver]

    if not dependency_configuration:
        return None

    return DownloadObserver(
        analyzer=None,
        patch_set=PatchSet.create(
            Patch.from_code_resource(
                __name__, "requires.py", **PatchContext.dump(dependency_configuration, target)
            )
        ),
    )
