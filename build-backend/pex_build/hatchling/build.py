# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import hatchling.build
import pex_build

# We re-export all hatchling's PEP-517 build backend hooks here for the build frontend to call.
from hatchling.build import *  # NOQA

if pex_build.TYPE_CHECKING:
    from typing import Any, Dict, List, Optional


def get_requires_for_build_wheel(config_settings=None):
    # type: (Optional[Dict[str, Any]]) -> List[str]

    reqs = hatchling.build.get_requires_for_build_wheel(
        config_settings=config_settings
    )  # type: List[str]
    if pex_build.INCLUDE_DOCS:
        with open("docs-requirements.txt") as fp:
            for raw_req in fp.readlines():
                req = raw_req.strip()
                if not req or req.startswith("#"):
                    continue
                reqs.append(req)
    return reqs
