# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest

from pex.finders import get_entry_point_from_console_script, get_script_from_distributions
from pex.pep_376 import InstalledWheel
from pex.pip.tool import get_pip
from pex.typing import TYPE_CHECKING
from pex.util import DistributionHelper

if TYPE_CHECKING:
    from typing import Any, Dict


# In-part, tests a bug where the wheel distribution name has dashes as reported in:
#   https://github.com/pantsbuild/pex/issues/443
#   https://github.com/pantsbuild/pex/issues/551
def test_get_script_from_distributions(tmpdir):
    # type: (Any) -> None
    whl_path = "./tests/example_packages/aws_cfn_bootstrap-1.4-py2-none-any.whl"
    install_dir = os.path.join(str(tmpdir), os.path.basename(whl_path))
    get_pip().spawn_install_wheel(wheel=whl_path, install_dir=install_dir).wait()

    dist = DistributionHelper.distribution_from_path(install_dir)
    assert dist is not None
    assert "aws-cfn-bootstrap" == dist.project_name

    dist_script = get_script_from_distributions("cfn-signal", [dist])
    assert dist_script.dist is dist
    assert InstalledWheel.load(install_dir).stashed_path("bin/cfn-signal") == dist_script.path
    assert dist_script.read_contents().startswith(
        b"#!"
    ), "Expected a `scripts`-style script w/shebang."

    assert None is get_script_from_distributions("non_existent_script", [dist])


class FakeDist(object):
    def __init__(self, key, console_script_entry):
        # type: (str, str) -> None
        self.key = key
        script = console_script_entry.split("=")[0].strip()
        self._entry_map = {"console_scripts": {script: console_script_entry}}

    def get_entry_map(self):
        # type: () -> Dict[str, Dict[str, str]]
        return self._entry_map


def test_get_entry_point_from_console_script():
    # type: () -> None
    dists = [
        FakeDist(key="fake", console_script_entry="bob= bob.main:run"),
        FakeDist(key="fake", console_script_entry="bob =bob.main:run"),
    ]

    dist, entrypoint = get_entry_point_from_console_script("bob", dists)
    assert "bob.main:run" == entrypoint
    assert dist in dists


def test_get_entry_point_from_console_script_conflict():
    # type: () -> None
    dists = [
        FakeDist(key="bob", console_script_entry="bob= bob.main:run"),
        FakeDist(key="fake", console_script_entry="bob =bob.main:run"),
    ]
    with pytest.raises(RuntimeError):
        get_entry_point_from_console_script("bob", dists)


def test_get_entry_point_from_console_script_dne():
    # type: () -> None
    dists = [
        FakeDist(key="bob", console_script_entry="bob= bob.main:run"),
        FakeDist(key="fake", console_script_entry="bob =bob.main:run"),
    ]
    assert (None, None) == get_entry_point_from_console_script("jane", dists)
