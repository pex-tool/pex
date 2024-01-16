# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
import sys
from typing import Any, Dict

from hatchling.metadata.plugin.interface import MetadataHookInterface


class DynamicRequiresPythonHook(MetadataHookInterface):
    """Allows dynamically specifying requires-python metadata via _PEX_REQUIRES_PYTHON env var."""

    PLUGIN_NAME = "pex-dynamic-requires-python"

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
