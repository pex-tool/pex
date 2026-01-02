# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import glob
import hashlib
import json
import os
import subprocess

from pex import hashing
from pex.atomic_directory import atomic_directory
from pex.compatibility import ConfigParser
from pex.targets import LocalInterpreter, Target, WheelEvaluation
from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper
from pex.venv.virtualenv import Virtualenv
from pex.version import __version__
from testing import PEX_TEST_DEV_ROOT, pex_project_dir

if TYPE_CHECKING:
    from typing import Iterable, List


def wheels():
    # type: () -> List[str]

    hasher = hashlib.sha1
    pex_dir = pex_project_dir()

    def file_hash(rel_path):
        # type: (str) -> str
        digest = hasher()
        hashing.file_hash(os.path.join(pex_dir, rel_path), digest=digest)
        return digest.hexdigest()

    def dir_hash(rel_path):
        # type: (str) -> str
        return CacheHelper.dir_hash(os.path.join(pex_dir, rel_path), hasher=hasher)

    pex_wheel_inputs_fingerprint = hasher(
        json.dumps(
            {
                "_PEX_REQUIRES_PYTHON": os.environ.get("_PEX_REQUIRES_PYTHON"),
                "build-system": {
                    "build-backend": dir_hash("build-backend"),
                    "pyproject.toml": file_hash("pyproject.toml"),
                    "setup.cfg": file_hash("setup.cfg"),
                    "setup.py": file_hash("setup.py"),
                },
                "code": dir_hash("pex"),
            },
        ).encode("utf-8")
    ).hexdigest()

    pex_wheel_dir = os.path.join(PEX_TEST_DEV_ROOT, "pex_wheels", "0", pex_wheel_inputs_fingerprint)
    with atomic_directory(pex_wheel_dir) as atomic_dir:
        if not atomic_dir.is_finalized():
            # The package command can be slow to run which locks up uv; so we just ensure a synced
            # uv venv (fast), then run the dev-cmd console script directly to avoid uv lock
            # timeouts in CI.
            subprocess.check_call(args=["uv", "sync", "--frozen"])
            subprocess.check_call(
                args=[
                    Virtualenv(".venv").bin_path("dev-cmd"),
                    "package",
                    "--",
                    "--no-pex",
                    "--additional-format",
                    "whl",
                    "--additional-format",
                    "whl-3.12-plus",
                    "--dist-dir",
                    atomic_dir.work_dir,
                ]
            )
    return glob.glob(os.path.join(pex_wheel_dir, "pex-{version}-*.whl".format(version=__version__)))


def select_best_wheel(
    whls,  # type: Iterable[str]
    target=LocalInterpreter.create(),  # type: Target
):
    # type: (...) -> str
    wheel_eval = WheelEvaluation.select_best_match(target.wheel_applies(whl) for whl in whls)
    assert (
        wheel_eval is not None
    ), "Expected a wheel from {wheels} to be compatible with {interpreter}".format(
        wheels=wheels, interpreter=target.render_description()
    )
    return wheel_eval.wheel


def wheel(target=LocalInterpreter.create()):
    # type: (Target) -> str
    return select_best_wheel(wheels(), target=target)


def requires_python():
    # type: () -> str

    requires_python_override = os.environ.get("_PEX_REQUIRES_PYTHON")
    if requires_python_override:
        return requires_python_override

    config_parser = ConfigParser()
    config_parser.read(os.path.join(pex_project_dir(), "setup.cfg"))
    return cast(str, config_parser.get("options", "python_requires"))
