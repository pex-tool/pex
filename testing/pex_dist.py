# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import json
import os

from pex import hashing
from pex.atomic_directory import atomic_directory
from pex.pip.version import PipVersion
from pex.util import CacheHelper
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from pex.version import __version__
from testing import PEX_TEST_DEV_ROOT, pex_project_dir


def wheel():
    # type: () -> str

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

    pex_wheel_dir = os.path.join(PEX_TEST_DEV_ROOT, "pex_wheels", pex_wheel_inputs_fingerprint)
    with atomic_directory(pex_wheel_dir, source="dist") as atomic_dir:
        if not atomic_dir.is_finalized():
            venv = Virtualenv.create(
                os.path.join(atomic_dir.work_dir, "venv"),
                install_pip=(
                    InstallationChoice.YES
                    if PipVersion.DEFAULT is PipVersion.VENDORED
                    else InstallationChoice.UPGRADED
                ),
                install_wheel=(
                    InstallationChoice.YES
                    if PipVersion.DEFAULT is PipVersion.VENDORED
                    else InstallationChoice.NO
                ),
            )
            dist_dir = os.path.join(atomic_dir.work_dir, "dist")
            if PipVersion.DEFAULT is PipVersion.VENDORED:
                venv.interpreter.execute(
                    args=[os.path.join(pex_dir, "setup.py"), "bdist_wheel", "-d", dist_dir]
                )
            else:
                venv.interpreter.execute(args=["-m", "pip", "wheel", pex_dir, "-w", dist_dir])
    return os.path.join(
        pex_wheel_dir, "pex-{version}-py2.py3-none-any.whl".format(version=__version__)
    )
