# Copyright 2014 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest

from pex.dist_metadata import CallableEntryPoint, DistMetadata, Distribution, EntryPoint
from pex.finders import (
    DistributionScript,
    get_entry_point_from_console_script,
    get_script_from_distributions,
)
from pex.pep_376 import InstalledWheel
from pex.pep_427 import install_wheel_chroot
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict, Text, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


# In-part, tests a bug where the wheel distribution name has dashes as reported in:
#   https://github.com/pex-tool/pex/issues/443
#   https://github.com/pex-tool/pex/issues/551
def test_get_script_from_distributions(tmpdir):
    # type: (Any) -> None

    def assert_script(dist):
        # type: (Distribution) -> Tuple[Distribution, DistributionScript]
        assert "aws-cfn-bootstrap" == dist.project_name

        dist_script = get_script_from_distributions("cfn-signal", [dist])
        assert dist_script is not None
        assert dist_script.dist is dist
        assert dist_script.read_contents().startswith(
            b"#!"
        ), "Expected a `scripts`-style script w/shebang."

        assert None is get_script_from_distributions("non_existent_script", [dist])
        return dist, dist_script

    whl_path = "./tests/example_packages/aws_cfn_bootstrap-1.4-py2-none-any.whl"
    _, dist_script = assert_script(Distribution.load(whl_path))
    assert "aws_cfn_bootstrap-1.4.data/scripts/cfn-signal" == dist_script.path

    install_dir = os.path.join(str(tmpdir), os.path.basename(whl_path))
    install_wheel_chroot(wheel_path=whl_path, destination=install_dir)
    installed_wheel_dist, dist_script = assert_script(Distribution.load(install_dir))
    assert InstalledWheel.load(install_dir).stashed_path("bin/cfn-signal") == dist_script.path


def create_dist(
    key,  # str
    console_script_entry,  # type: str
):
    # type: (...) -> Distribution
    entry_point = EntryPoint.parse(console_script_entry)

    @attr.s(frozen=True)
    class FakeDist(Distribution):
        def get_entry_map(self):
            # type: () -> Dict[Text, Dict[Text, EntryPoint]]
            return {"console_scripts": {entry_point.name: entry_point}}

    return FakeDist(
        location=os.getcwd(),
        metadata=DistMetadata(
            project_name=ProjectName(key),
            version=Version("1.0"),
        ),
    )


def test_get_entry_point_from_console_script():
    # type: () -> None
    dists = [
        create_dist(key="fake", console_script_entry="bob= bob.main:run"),
        create_dist(key="fake", console_script_entry="bob =bob.main:run"),
    ]

    dist_entrypoint = get_entry_point_from_console_script("bob", dists)
    assert dist_entrypoint is not None
    assert (
        CallableEntryPoint(name="bob", module="bob.main", attrs=("run",))
        == dist_entrypoint.entry_point
    )
    assert dist_entrypoint.dist in dists


def test_get_entry_point_from_console_script_conflict():
    # type: () -> None
    dists = [
        create_dist(key="bob", console_script_entry="bob= bob.main:run"),
        create_dist(key="fake", console_script_entry="bob =bob.main:run"),
    ]
    with pytest.raises(RuntimeError):
        get_entry_point_from_console_script("bob", dists)


def test_get_entry_point_from_console_script_dne():
    # type: () -> None
    dists = [
        create_dist(key="bob", console_script_entry="bob= bob.main:run"),
        create_dist(key="fake", console_script_entry="bob =bob.main:run"),
    ]
    assert get_entry_point_from_console_script("jane", dists) is None
