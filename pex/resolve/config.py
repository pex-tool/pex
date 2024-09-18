# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.pip.installation import compatible_version, validate_targets
from pex.pip.version import PipVersionValue
from pex.resolve.resolver_configuration import (
    LockRepositoryConfiguration,
    PexRepositoryConfiguration,
    PipConfiguration,
    PreResolvedConfiguration,
)
from pex.result import Error, catch, try_
from pex.targets import Targets
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Optional, TypeVar, Union

    import attr  # vendor:skip

    Configuration = Union[
        LockRepositoryConfiguration,
        PexRepositoryConfiguration,
        PreResolvedConfiguration,
        PipConfiguration,
    ]
    _C = TypeVar("_C", bound=Configuration)

else:
    from pex.third_party import attr


def _finalize_pip_configuration(
    pip_configuration,  # type: PipConfiguration
    targets,  # type: Targets
    context,  # type: str
    pip_version=None,  # type: Optional[PipVersionValue]
):
    # type: (...) -> Union[PipConfiguration, Error]
    version = pip_version or pip_configuration.version
    if version and pip_configuration.allow_version_fallback:
        return attr.evolve(
            pip_configuration, version=try_(compatible_version(targets, version, context))
        )

    result = catch(validate_targets, targets, version, context)
    if isinstance(result, Error):
        return result
    return attr.evolve(pip_configuration, version=version)


def finalize(
    resolver_configuration,  # type: _C
    targets,  # type: Targets
    context,  # type: str
    pip_version=None,  # type: Optional[PipVersionValue]
):
    # type: (...) -> Union[_C, Error]

    if isinstance(resolver_configuration, PipConfiguration):
        return cast(
            "_C",
            _finalize_pip_configuration(
                resolver_configuration, targets, context, pip_version=pip_version
            ),
        )

    if isinstance(resolver_configuration, (PexRepositoryConfiguration, PreResolvedConfiguration)):
        pip_configuration = try_(
            _finalize_pip_configuration(
                resolver_configuration.pip_configuration,
                targets,
                context,
                pip_version=pip_version,
            )
        )
        return cast("_C", attr.evolve(resolver_configuration, pip_configuration=pip_configuration))

    if isinstance(resolver_configuration, LockRepositoryConfiguration):
        lock_file = try_(resolver_configuration.parse_lock())
        pip_configuration = try_(
            _finalize_pip_configuration(
                resolver_configuration.pip_configuration,
                targets,
                context,
                pip_version=pip_version or lock_file.pip_version,
            )
        )
        return cast(
            "_C",
            attr.evolve(
                resolver_configuration,
                parse_lock=lambda: lock_file,
                pip_configuration=pip_configuration,
            ),
        )

    return resolver_configuration
