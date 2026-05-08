# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.enum import Enum
from pex.sysconfig import SysPlatform
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class Url(str):
    pass


class File(str):
    pass


class CompressionMethod(Enum["CompressionMethod.Value"]):
    class Value(Enum.Value):
        pass

    DEFLATED = Value("deflated")
    ZSTD = Value("zstd")


CompressionMethod.seal()


@attr.s(frozen=True)
class NativeRuntimeConfiguration(object):
    max_jobs = attr.ib(default=None)  # type: Optional[int]
    platforms = attr.ib(default=())  # type: Tuple[SysPlatform.Value, ...]
    pexrc_binary = attr.ib(default=None)  # type: Optional[Union[File, Url]]
    compression_method = attr.ib(default=None)  # type: Optional[CompressionMethod.Value]
    compression_level = attr.ib(default=None)  # type: Optional[int]
