# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.enum import Enum
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class TargetSystem(Enum["TargetSystem.Value"]):
    class Value(Enum.Value):
        pass

    LINUX = Value("linux")
    MAC = Value("mac")
    WINDOWS = Value("windows")


TargetSystem.seal()


@attr.s(frozen=True)
class UniversalTarget(object):
    requires_python = attr.ib(default=())  # type: Tuple[str, ...]
    systems = attr.ib(default=())  # type: Tuple[TargetSystem.Value, ...]
