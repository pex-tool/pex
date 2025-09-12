# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import logging

logger = logging.getLogger(__name__)


def patch():
    # type: () -> None

    from pex.pep_508 import MarkerEnvironment
    from pex.pip.package_repositories import PatchContext
    from pex.typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from typing import Dict, Optional

    patch_context = PatchContext.load()
    target = patch_context.target

    marker_environment = None  # type: Optional[Dict[str, str]]
    if isinstance(target, MarkerEnvironment):
        marker_environment = target.as_dict()

    # TODO: XXX: Support patching Pip's collector.py to customize links / find-links per
    #  project name
    logger.debug(str(marker_environment))
