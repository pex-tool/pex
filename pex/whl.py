# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import os

from pex.atomic_directory import atomic_directory
from pex.cache.dirs import CacheDir
from pex.dist_metadata import Distribution
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.installed_wheel import InstalledWheel
from pex.pep_427 import repack
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper

if TYPE_CHECKING:
    from typing import Optional, Union


def repacked_whl(
    installed_wheel,  # type: Union[str, InstalledWheel]
    fingerprint,  # type: str
    distribution_name=None,  # type: Optional[str]
    use_system_time=False,  # type: bool
):
    # type: (...) -> FingerprintedDistribution

    installed_wheel = (
        installed_wheel
        if isinstance(installed_wheel, InstalledWheel)
        else InstalledWheel.load(installed_wheel)
    )

    repack_dir = CacheDir.REPACKED_WHEELS.path(fingerprint)
    with atomic_directory(target_dir=repack_dir) as atomic_dir:
        if not atomic_dir.is_finalized():
            whl = repack(
                installed_wheel=installed_wheel,
                dest_dir=atomic_dir.work_dir,
                # N.B.: Some compressed tag set wheels in the wild have a wheel filename with tags
                # in a different order from their WHEEL metadata; e.g.:
                #   cffi-2.0.0-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
                # vs its WHEEL metadata:
                #   Wheel-Version: 1.0
                #   Generator: setuptools (80.9.0)
                #   Root-Is-Purelib: false
                #   Tag: cp310-cp310-manylinux_2_17_x86_64
                #   Tag: cp310-cp310-manylinux2014_x86_64
                #
                # This override allows higher levels to adjust for this.
                override_wheel_file_name=distribution_name,
                use_system_time=use_system_time,
            )
            with open(os.path.join(atomic_dir.work_dir, "FINGERPRINT"), "w") as fp:
                fp.write(CacheHelper.hash(whl, hasher=hashlib.sha256))

    with open(os.path.join(repack_dir, "FINGERPRINT")) as fp:
        fingerprint = fp.read()

    return FingerprintedDistribution(
        distribution=Distribution.load(
            os.path.join(repack_dir, distribution_name or installed_wheel.wheel_file_name())
        ),
        fingerprint=fingerprint,
    )
