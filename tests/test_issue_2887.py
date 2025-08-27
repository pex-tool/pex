# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import re

import pytest

from pex.dist_metadata import Requirement
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex_warnings import PEXWarning
from pex.resolve import abbreviated_platforms
from pex.resolve.lockfile.pep_751 import Pylock
from pex.result import try_
from pex.targets import AbbreviatedPlatform
from testing import data


def test_package_with_no_artifacts():
    # type: () -> None

    pylock_path = data.path("locks", "pylock.issue-2887.toml")
    with pytest.warns(
        PEXWarning,
        match=re.escape(
            'Skipping package at packages[47]{{name = "nvidia-cublas-cu12"}} in {lock} since it '
            "defines no artifacts.".format(lock=pylock_path)
        ),
    ):
        pylock = try_(Pylock.parse(pylock_path))

    resolved_packages = try_(
        pylock.resolve(
            target=AbbreviatedPlatform.create(
                abbreviated_platforms.create("linux-x86_64-cp-313-cp313", manylinux="manylinux2014")
            ),
            requirements=[Requirement.parse("nvidia-cudnn-cu12")],
        )
    )
    assert [
        (ProjectName("nvidia-cudnn-cu12"), Version("9.1.0.70")),
        (ProjectName("nvidia-cublas-cu12"), Version("12.4.5.8")),
    ] == [(package.project_name, package.version) for package in resolved_packages.packages]
