# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import LockedRequirement
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.model import Lockfile
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Mapping, Union


def index_lock_artifacts(lock_file):
    # type: (Union[str, Lockfile]) -> Mapping[ProjectName, LockedRequirement]

    lock = lock_file if isinstance(lock_file, Lockfile) else json_codec.load(lock_file)
    assert 1 == len(lock.locked_resolves)
    locked_resolve = lock.locked_resolves[0]
    return {
        locked_requirement.pin.project_name: locked_requirement
        for locked_requirement in locked_resolve.locked_requirements
    }
