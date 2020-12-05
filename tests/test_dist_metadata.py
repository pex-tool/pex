# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
from contextlib import contextmanager

from pex.common import temporary_dir
from pex.dist_metadata import requires_dists, requires_python
from pex.pip import get_pip
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.pkg_resources import Distribution, Requirement
from pex.util import DistributionHelper


def install_wheel(
    wheel_path,  # type: str
    install_dir,  # type: str
):
    # type: (...) -> Distribution
    get_pip().spawn_install_wheel(wheel=wheel_path, install_dir=install_dir).wait()
    dist = DistributionHelper.distribution_from_path(install_dir)
    assert dist is not None, "Could not load a distribution from {}".format(install_dir)
    return dist


def example_package(name):
    # type: (str) -> str
    return os.path.join("./tests/example_packages", name)


@contextmanager
def example_distribution(name):
    # type: (str) -> Distribution
    wheel_path = example_package(name)
    with temporary_dir() as install_dir:
        yield install_wheel(wheel_path, install_dir=install_dir)


@contextmanager
def resolved_distribution(requirement):
    # type: (str) -> Distribution
    with temporary_dir() as td:
        download_dir = os.path.join(td, "download")
        get_pip().spawn_download_distributions(
            download_dir=download_dir, requirements=[requirement], transitive=False
        ).wait()
        wheels = os.listdir(download_dir)
        assert len(wheels) == 1, "Expected 1 wheel to be downloaded for {}".format(requirement)
        wheel_path = os.path.join(download_dir, wheels[0])
        install_dir = os.path.join(td, "install")
        yield install_wheel(wheel_path, install_dir=install_dir)


def test_requires_python():
    # type: () -> None
    with resolved_distribution("pex==2.1.21") as dist:
        assert SpecifierSet(
            ">=2.7,<=3.9,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*"
        ) == requires_python(dist)


def test_requires_python_none():
    # type: () -> None
    with example_distribution("aws_cfn_bootstrap-1.4-py2-none-any.whl") as dist:
        assert requires_python(dist) is None


def test_requires_dists():
    # type: () -> None
    with example_distribution("aws_cfn_bootstrap-1.4-py2-none-any.whl") as dist:
        assert [
            Requirement.parse(req)
            for req in (
                "python-daemon>=1.5.2,<2.0",
                "pystache>=0.4.0",
                "setuptools",
            )
        ] == list(requires_dists(dist))


def test_requires_dists_none():
    # type: () -> None
    with example_distribution("MarkupSafe-1.0-cp27-cp27mu-linux_x86_64.whl") as dist:
        assert [] == list(requires_dists(dist))
