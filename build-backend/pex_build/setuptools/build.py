# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import os.path
import subprocess
import sys
from zipfile import ZIP_DEFLATED

import pex_build
import setuptools.build_meta

# We re-export all setuptools' PEP-517 build backend hooks here for the build frontend to call.
from setuptools.build_meta import *  # NOQA

from pex import hashing, requirements
from pex.common import open_zip, temporary_dir
from pex.orderedset import OrderedSet
from pex.pep_376 import Hash, InstalledFile, Record
from pex.version import __version__

if pex_build.TYPE_CHECKING:
    from typing import Any, Dict, List, Optional


def get_requires_for_build_wheel(config_settings=None):
    # type: (Optional[Dict[str, Any]]) -> List[str]

    reqs = OrderedSet(
        setuptools.build_meta.get_requires_for_build_wheel(config_settings=config_settings)
    )  # type: OrderedSet[str]
    if pex_build.INCLUDE_DOCS:
        reqs.update(
            str(req) for req in requirements.parse_requirement_file("docs-requirements.txt")
        )
    return list(reqs)


def build_wheel(
    wheel_directory,  # type: str
    config_settings=None,  # type: Optional[Dict[str, Any]]
    metadata_directory=None,  # type: Optional[str]
):
    # type: (...) -> str

    wheel = setuptools.build_meta.build_wheel(
        wheel_directory, config_settings=config_settings, metadata_directory=metadata_directory
    )  # type: str
    if pex_build.INCLUDE_DOCS:
        wheel_path = os.path.join(wheel_directory, wheel)
        with temporary_dir() as chroot:
            with open_zip(wheel_path) as zip_fp:
                zip_fp.extractall(chroot)

            out_dir = os.path.join(chroot, "pex", "docs")
            subprocess.check_call(
                args=[
                    sys.executable,
                    os.path.join("scripts", "build-docs.py"),
                    "--clean-html",
                    out_dir,
                ]
            )
            dist_info_dir = "pex-{version}.dist-info".format(version=__version__)
            record_path = os.path.join(chroot, dist_info_dir, "RECORD")
            with open(record_path) as fp:
                installed_files = list(Record.read(fp))
            for root, _, files in os.walk(out_dir):
                for f in files:
                    src = os.path.join(root, f)
                    dst = os.path.relpath(src, chroot)
                    hasher = hashlib.sha256()
                    hashing.file_hash(src, digest=hasher)
                    installed_files.append(
                        InstalledFile(path=dst, hash=Hash.create(hasher), size=os.path.getsize(src))
                    )
            Record.write(record_path, installed_files)
            with open_zip(wheel_path, "w", compression=ZIP_DEFLATED) as zip_fp:

                def add_top_level_dir(name):
                    # type: (str) -> None
                    top = os.path.join(chroot, name)
                    zip_fp.write(top, name + "/")
                    for root, dirs, files in os.walk(top):
                        dirs[:] = sorted(dirs)
                        for path in sorted(files) + dirs:
                            src = os.path.join(root, path)
                            dst = os.path.relpath(src, chroot)
                            zip_fp.write(src, dst)

                add_top_level_dir("pex")
                add_top_level_dir(dist_info_dir)

    return wheel
