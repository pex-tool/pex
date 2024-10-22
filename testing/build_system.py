# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import os
import sys

import pytest

from pex.build_system.pep_517 import build_sdist
from pex.dist_metadata import Distribution
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pip.installation import get_pip
from pex.pip.version import PipVersion
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.resolver_configuration import PipConfiguration, ResolverVersion
from pex.result import Error
from pex.targets import LocalInterpreter
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


hatchling_only_supports_37_and_greater = pytest.mark.skipif(
    sys.version_info[:2] < (3, 7), reason="Our current build system only works under Python>=3.7"
)


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

    # This test utility is used by all versions of Python Pex supports; so we need to use a Pip
    # setup which is guaranteed to work with the current Python version.
    pip_version = PipVersion.DEFAULT
    resolver_version = ResolverVersion.default(pip_version)

    target = LocalInterpreter.create()
    resolver = ConfiguredResolver(
        PipConfiguration(version=pip_version, resolver_version=resolver_version)
    )
    location = build_sdist(
        project_dir,
        sdist_dir,
        target,
        resolver,
        pip_version=pip_version,
    )
    assert not isinstance(location, Error), location
    assert sdist_dir == os.path.dirname(location)

    sdist = Distribution.load(str(location))
    assert_expected_dist(sdist)

    # Verify the sdist is valid such that we can build a wheel from it.
    wheel_dir = os.path.join(str(tmpdir), "wheel_dir")
    get_pip(resolver=resolver).spawn_build_wheels(
        distributions=[sdist.location], wheel_dir=wheel_dir
    ).wait()
    wheels = glob.glob(os.path.join(wheel_dir, "*.whl"))
    assert 1 == len(wheels)
    assert_expected_dist(Distribution.load(wheels[0]))
