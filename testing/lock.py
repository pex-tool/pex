# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.interpreter_constraints import InterpreterConstraint
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import LockedRequirement
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.model import Lockfile
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import List, Mapping, Union


def index_lock_artifacts(lock_file):
    # type: (Union[str, Lockfile]) -> Mapping[ProjectName, LockedRequirement]

    lock = lock_file if isinstance(lock_file, Lockfile) else json_codec.load(lock_file)
    assert 1 == len(lock.locked_resolves)
    locked_resolve = lock.locked_resolves[0]
    return {
        locked_requirement.pin.project_name: locked_requirement
        for locked_requirement in locked_resolve.locked_requirements
    }


def extract_lock_option_args(lock_file):
    # type: (Union[str, Lockfile]) -> List[str]

    lock = lock_file if isinstance(lock_file, Lockfile) else json_codec.load(lock_file)
    lock_args = [
        "--pip-version",
        str(lock.pip_version),
        "--resolver-version",
        str(lock.resolver_version),
        "--style",
        str(lock.style),
    ]
    for requires_python in lock.requires_python:
        lock_args.append("--interpreter-constraint")
        lock_args.append(str(InterpreterConstraint.parse(requires_python)))
    for target_system in lock.target_systems:
        lock_args.append("--target-system")
        lock_args.append(str(target_system))
    return lock_args
