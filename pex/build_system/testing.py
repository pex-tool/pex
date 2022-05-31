# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import os

from pex.build_system.pep_517 import build_sdist
from pex.dist_metadata import Distribution
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pip.tool import get_pip
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.result import Error
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def assert_build_sdist(
    project_dir,  # type: str
    project_name,  # type: str
    version,  # type: str
    tmpdir,  # type: Any
):
    # type: (...) -> None

    def assert_expected_dist(dist):
        # type: (Distribution) -> None
        assert ProjectName(project_name) == dist.metadata.project_name
        assert Version(version) == dist.metadata.version

    sdist_dir = os.path.join(str(tmpdir), "sdist_dir")
    location = build_sdist(project_dir, sdist_dir, ConfiguredResolver.default())
    assert not isinstance(location, Error)
    assert sdist_dir == os.path.dirname(location)

    sdist = Distribution.load(location)
    assert_expected_dist(sdist)

    # Verify the sdist is valid such that we can build a wheel from it.
    wheel_dir = os.path.join(str(tmpdir), "wheel_dir")
    get_pip().spawn_build_wheels(distributions=[sdist.location], wheel_dir=wheel_dir).wait()
    wheels = glob.glob(os.path.join(wheel_dir, "*.whl"))
    assert 1 == len(wheels)
    assert_expected_dist(Distribution.load(wheels[0]))
