# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os.path
import subprocess
import sys

import pex_build
from hatchling.builders.hooks.plugin.interface import BuildHookInterface

if pex_build.TYPE_CHECKING:
    from typing import Any, Dict


class AdjustBuild(BuildHookInterface):
    """Allows alteration of the build process."""

    PLUGIN_NAME = "pex-adjust-build"

    def initialize(
        self,
        version,  # type: str
        build_data,  # type: Dict[str, Any]
    ):
        # type: (...) -> None
        if pex_build.INCLUDE_DOCS:
            out_dir = os.path.join(self.root, "dist", "docs")
            subprocess.check_call(
                args=[
                    sys.executable,
                    os.path.join(self.root, "scripts", "build_docs.py"),
                    "--clean-html",
                    out_dir,
                ]
            )
            build_data["force_include"][out_dir] = os.path.join("pex", "docs")
