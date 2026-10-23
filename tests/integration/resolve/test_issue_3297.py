# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import sys

import pytest

from pex.pep_503 import ProjectName
from pex.pip.version import PipVersion
from pex.resolve.lockfile import json_codec
from pex.typing import TYPE_CHECKING
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    pass


@pytest.mark.skipif(
    PipVersion.DEFAULT < PipVersion.v23_2,
    reason=(
        "Pip prior to 23.2 does not accept direct URLs with markers which are required for this "
        "test."
    ),
)
def test_split_universal_lock_sync(tmpdir):
    # type: (Tempdir) -> None

    lock_file = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--style",
        "universal",
        "--interpreter-constraint",
        "=={major}.{minor}.*".format(major=sys.version_info[0], minor=sys.version_info[1]),
        "--target-system",
        "linux",
        "--target-system",
        "mac",
        "-o",
        lock_file,
        "--indent",
        "2",
        "cowsay<6; sys_platform == 'linux'",
        (
            "cowsay @ "
            "https://files.pythonhosted.org/packages/"
            "6b/b8/9f497fd045d74fe21d91cbe8debae0b451229989e35b539d218547d79fc6/cowsay-5.0.tar.gz "
            "; sys_platform == 'darwin'"
        ),
    ).assert_success()

    run_pex3(
        "lock",
        "sync",
        "--lock",
        lock_file,
        "--style",
        "universal",
        "--interpreter-constraint",
        "=={major}.{minor}.*".format(major=sys.version_info[0], minor=sys.version_info[1]),
        "--target-system",
        "linux",
        "--target-system",
        "mac",
        "ansicolors",
        "cowsay<6; sys_platform == 'linux'",
        (
            "cowsay @ "
            "https://files.pythonhosted.org/packages/"
            "6b/b8/9f497fd045d74fe21d91cbe8debae0b451229989e35b539d218547d79fc6/cowsay-5.0.tar.gz "
            "; sys_platform == 'darwin'"
        ),
    ).assert_success()

    lock = json_codec.load(lock_file)
    assert 2 == len(lock.locked_resolves)
    for index, locked_resolve in enumerate(lock.locked_resolves):
        assert {ProjectName("ansicolors"), ProjectName("cowsay")} == {
            locked_requirement.pin.project_name
            for locked_requirement in locked_resolve.locked_requirements
        }, "Unexpected lock[{index}] platform_tag={platform_tag} marker={marker}".format(
            index=index, platform_tag=locked_resolve.platform_tag, marker=locked_resolve.marker
        )
