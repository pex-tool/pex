# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
import sys

import pex_build
from hatchling.metadata.plugin.interface import MetadataHookInterface

if pex_build.TYPE_CHECKING:
    from typing import Any, Dict


def expand_value(
    value,  # type: Any
    **fmt  # type: str
):
    # type: (...) -> Any
    if isinstance(value, str):
        return value.format(**fmt)
    if isinstance(value, list):
        return [expand_value(val) for val in value]
    if isinstance(value, dict):
        return {key: expand_value(value, **fmt) for key, value in value.items()}
    return value


class AdjustMetadata(MetadataHookInterface):
    """Allows modifying project metadata.

    The following mutations are supported:
    + Specifying alternate requires-python metadata via _PEX_REQUIRES_PYTHON env var.
    + Expanding format string placeholder (`{name}`) with metadata values via the `expand` mapping of placeholder name
      to metadata value.
    """

    PLUGIN_NAME = "pex-adjust-metadata"

    def update(self, metadata):
        # type: (Dict[str, Any]) -> None
        requires_python = os.environ.get("_PEX_REQUIRES_PYTHON")
        if requires_python:
            print(
                "pex_build: Dynamically modifying pyproject.toml requires-python of {original} to "
                "{dynamic}".format(original=metadata["requires-python"], dynamic=requires_python),
                file=sys.stderr,
            )
            metadata["requires-python"] = requires_python

        expand = self.config.get("expand")
        if expand:
            metadata.update(
                (
                    key,
                    expand_value(value, **{key: metadata[value] for key, value in expand.items()}),
                )
                for key, value in metadata.items()
                if key != "version"
            )
