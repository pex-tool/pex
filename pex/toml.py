# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import sys
from io import BytesIO

from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Dict, Union

TOMLI_SUPPORTED = sys.version_info[:2] >= (3, 7)


if not TOMLI_SUPPORTED:
    from pex.third_party.toml import TomlDecodeError as _TomlDecodeError
    from pex.third_party.toml import dump as _dump
    from pex.third_party.toml import dumps as _dumps
    from pex.third_party.toml import load as _load
    from pex.third_party.toml import loads as _loads

    def load(source):
        # type: (Union[str, BytesIO]) -> Dict[str, Any]
        if isinstance(source, str):
            return cast("Dict[str, Any]", _load(source))
        else:
            return cast("Dict[str, Any]", _loads(source.read().decode("utf-8")))

    def dump(
        data,  # type: Dict[str, Any]
        fp,  # type: BytesIO
    ):
        # type: (...) -> None
        fp.write(_dumps(data).encode("utf-8"))

else:
    from pex.third_party.tomli import TOMLDecodeError as _TomlDecodeError
    from pex.third_party.tomli import load as _load
    from pex.third_party.tomli import loads as _loads
    from pex.third_party.tomli_w import dump as _dump
    from pex.third_party.tomli_w import dumps as _dumps

    def load(source):
        # type: (Union[str, BytesIO]) -> Dict[str, Any]
        if isinstance(source, str):
            with open(source, "rb") as fp:
                return cast("Dict[str, Any]", _load(fp))
        else:
            return cast("Dict[str, Any]", _load(source))

    def dump(
        data,  # type: Dict[str, Any]
        fp,  # type: BytesIO
    ):
        # type: (...) -> None
        _dump(data, fp)


loads = _loads
TomlDecodeError = _TomlDecodeError
dumps = _dumps
