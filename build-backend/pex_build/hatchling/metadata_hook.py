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
    + Expanding format string placeholder (`{name}`) with metadata values via the `expand` mapping
      of placeholder name to metadata value.
    """

    PLUGIN_NAME = "pex-adjust-metadata"

    def update(self, metadata):
        # type: (Dict[str, Any]) -> None

        dynamic_metadata = self.config.get("project")
        if not dynamic_metadata:
            return

        self._update_requires_python(metadata, dynamic_metadata)
        self._expand_placeholders(metadata, dynamic_metadata)

    def _update_requires_python(
        self,
        metadata,  # type: Dict[str, Any]
        dynamic_metadata,  # type: Dict[str, Any]
    ):
        # type: (...) -> None

        dynamic_requires_python = os.environ.get("_PEX_REQUIRES_PYTHON")
        static_requires_python = dynamic_metadata.get("requires-python")

        if dynamic_requires_python:
            if not static_requires_python:
                raise ValueError(
                    "A dynamic override of requires-python metadata was specified via "
                    "`_PEX_REQUIRES_PYTHON={dynamic_requires_python}` but there was no "
                    "corresponding static value defined in "
                    "`tool.hatch.metadata.hooks.{plugin_name}.project`.".format(
                        plugin_name=self.PLUGIN_NAME,
                        dynamic_requires_python=dynamic_requires_python,
                    )
                )

            print(
                "pex_build: Dynamically modifying pyproject.toml requires-python of {original} to "
                "{dynamic}".format(
                    original=static_requires_python, dynamic=dynamic_requires_python
                ),
                file=sys.stderr,
            )
            dynamic_metadata["requires-python"] = dynamic_requires_python

        if dynamic_metadata["requires-python"]:
            metadata["requires-python"] = dynamic_metadata["requires-python"]

    def _expand_placeholders(
        self,
        metadata,  # type: Dict[str, Any]
        dynamic_metadata,  # type: Dict[str, Any]
    ):
        # type: (...) -> None

        expand = self.config.get("expand")
        if not expand:
            return

        metadata.update(
            (
                key,
                expand_value(value, **{key: metadata[value] for key, value in expand.items()}),
            )
            for key, value in dynamic_metadata.items()
        )
