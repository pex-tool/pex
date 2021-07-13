# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import tarfile
import warnings
from contextlib import contextmanager
from textwrap import dedent

import pytest

from pex.common import open_zip, temporary_dir
from pex.dist_metadata import (
    MetadataError,
    ProjectNameAndVersion,
    find_dist_info_file,
    project_name_and_version,
    requires_dists,
    requires_python,
)
from pex.pex_warnings import PEXWarning
from pex.pip import get_pip
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.pkg_resources import Distribution, Requirement
from pex.typing import TYPE_CHECKING
from pex.util import DistributionHelper
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import Tuple, Iterator, Any


@contextmanager
def installed_wheel(wheel_path):
    # type: (str) -> Iterator[Distribution]
    with temporary_dir() as install_dir:
        get_pip().spawn_install_wheel(wheel=wheel_path, install_dir=install_dir).wait()
        dist = DistributionHelper.distribution_from_path(install_dir)
        assert dist is not None, "Could not load a distribution from {}.".format(install_dir)
        yield dist


@contextmanager
def example_distribution(name):
    # type: (str) -> Iterator[Tuple[str, Distribution]]
    wheel_path = os.path.join("./tests/example_packages", name)
    with installed_wheel(wheel_path) as distribution:
        yield wheel_path, distribution


@contextmanager
def downloaded_sdist(requirement):
    # type: (str) -> Iterator[str]
    with temporary_dir() as td:
        download_dir = os.path.join(td, "download")
        get_pip().spawn_download_distributions(
            download_dir=download_dir,
            requirements=[requirement],
            transitive=False,
            use_wheel=False,
        ).wait()
        dists = os.listdir(download_dir)
        assert len(dists) == 1, "Expected 1 dist to be downloaded for {}.".format(requirement)
        sdist = os.path.join(download_dir, dists[0])
        assert sdist.endswith((".sdist", ".tar.gz", ".zip"))
        yield sdist


def as_requirement(project_name_and_version):
    # type: (ProjectNameAndVersion) -> str
    return "{}=={}".format(project_name_and_version.project_name, project_name_and_version.version)


PYGOOGLEEARTH_PROJECT_NAME_AND_VERSION = ProjectNameAndVersion("pygoogleearth", "0.0.2")


@pytest.fixture(scope="module")
def pygoogleearth_zip_sdist():
    # type: () -> Iterator[str]
    with downloaded_sdist(as_requirement(PYGOOGLEEARTH_PROJECT_NAME_AND_VERSION)) as sdist:
        assert sdist.endswith(".zip")
        yield sdist


PIP_PROJECT_NAME_AND_VERSION = ProjectNameAndVersion("pip", "20.3.1")


@pytest.fixture(scope="module")
def pip_tgz_sdist():
    # type: () -> Iterator[str]
    with downloaded_sdist(as_requirement(PIP_PROJECT_NAME_AND_VERSION)) as sdist:
        assert sdist.endswith(".tar.gz")
        yield sdist


@pytest.fixture(scope="module")
def pip_wheel(pip_tgz_sdist):
    # type: (str) -> Iterator[str]
    with temporary_dir() as wheel_dir:
        get_pip().spawn_build_wheels([pip_tgz_sdist], wheel_dir=wheel_dir).wait()
        wheels = os.listdir(wheel_dir)
        assert len(wheels) == 1, "Expected 1 wheel to be built for {}.".format(pip_tgz_sdist)
        wheel = os.path.join(wheel_dir, wheels[0])
        assert wheel.endswith(".whl")
        yield wheel


@pytest.fixture(scope="module")
def pip_distribution(pip_wheel):
    # type: (str) -> Iterator[Distribution]
    with installed_wheel(pip_wheel) as distribution:
        yield distribution


def test_project_name_and_version_from_filename(
    pygoogleearth_zip_sdist,  # type: str
    pip_tgz_sdist,  # type: str
    pip_wheel,  # type: str
):
    # type: (...) -> None
    assert PYGOOGLEEARTH_PROJECT_NAME_AND_VERSION == ProjectNameAndVersion.from_filename(
        pygoogleearth_zip_sdist
    )
    assert PIP_PROJECT_NAME_AND_VERSION == ProjectNameAndVersion.from_filename(pip_tgz_sdist)
    assert PIP_PROJECT_NAME_AND_VERSION == ProjectNameAndVersion.from_filename(pip_wheel)


def test_project_name_and_version_from_filename_pep625():
    # type: () -> None
    assert ProjectNameAndVersion(
        "a-distribution-name", "1.2.3"
    ) == ProjectNameAndVersion.from_filename("a-distribution-name-1.2.3.sdist")


def test_project_name_and_version_from_filename_invalid():
    # type: () -> None
    with pytest.raises(MetadataError):
        ProjectNameAndVersion.from_filename("unknown_distribution.format")


def test_project_name_and_version_from_metadata(
    pygoogleearth_zip_sdist,  # type: str
    pip_tgz_sdist,  # type: str
    pip_wheel,  # type: str
    pip_distribution,  # type: Distribution
):
    # type: (...) -> None
    assert PYGOOGLEEARTH_PROJECT_NAME_AND_VERSION == project_name_and_version(
        pygoogleearth_zip_sdist, fallback_to_filename=False
    )
    assert PIP_PROJECT_NAME_AND_VERSION == project_name_and_version(
        pip_tgz_sdist, fallback_to_filename=False
    )
    assert PIP_PROJECT_NAME_AND_VERSION == project_name_and_version(
        pip_wheel, fallback_to_filename=False
    )
    assert PIP_PROJECT_NAME_AND_VERSION == project_name_and_version(
        pip_distribution, fallback_to_filename=False
    )


def test_project_name_and_version_fallback(tmpdir):
    # type: (Any) -> None
    def tmp_path(relpath):
        # type: (str) -> str
        return os.path.join(str(tmpdir), relpath)

    expected_metadata_project_name_and_version = ProjectNameAndVersion("foo", "1.2.3")

    pkg_info_src = tmp_path("PKG-INFO")
    with open(pkg_info_src, "w") as fp:
        fp.write("Name: {}\n".format(expected_metadata_project_name_and_version.project_name))
        fp.write("Version: {}\n".format(expected_metadata_project_name_and_version.version))

    sdist_path = tmp_path("bar-baz-4.5.6.tar.gz")
    with tarfile.open(sdist_path, mode="w:gz") as tf:
        # N.B.: Valid PKG-INFO at an invalid location.
        tf.add(pkg_info_src, arcname="PKG-INFO")

    with ENV.patch(PEX_EMIT_WARNINGS="True"), warnings.catch_warnings(record=True) as events:
        assert project_name_and_version(sdist_path, fallback_to_filename=False) is None
        assert 1 == len(events)
        warning = events[0]
        assert PEXWarning == warning.category
        assert "bar-baz-4.5.6/PKG-INFO" in str(warning.message)

    assert ProjectNameAndVersion("bar-baz", "4.5.6") == project_name_and_version(
        sdist_path, fallback_to_filename=True
    )

    name_and_version = "eggs-7.8.9"
    pkf_info_path = "{}/PKG-INFO".format(name_and_version)

    def write_sdist_tgz(extension):
        sdist_path = tmp_path("{}.{}".format(name_and_version, extension))
        with tarfile.open(sdist_path, mode="w:gz") as tf:
            tf.add(pkg_info_src, arcname=pkf_info_path)
        return sdist_path

    assert expected_metadata_project_name_and_version == project_name_and_version(
        write_sdist_tgz("tar.gz"), fallback_to_filename=False
    )
    assert expected_metadata_project_name_and_version == project_name_and_version(
        write_sdist_tgz("sdist"), fallback_to_filename=False
    )

    zip_sdist_path = tmp_path("{}.zip".format(name_and_version))
    with open_zip(zip_sdist_path, mode="w") as zf:
        zf.write(pkg_info_src, arcname=pkf_info_path)

    assert expected_metadata_project_name_and_version == project_name_and_version(
        zip_sdist_path, fallback_to_filename=False
    )


def test_requires_python(
    pip_tgz_sdist,  # type: str
    pip_wheel,  # type: str
    pip_distribution,  # type: Distribution
):
    # type: (...) -> None
    expected_requires_python = SpecifierSet(">=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*")
    assert expected_requires_python == requires_python(pip_tgz_sdist)
    assert expected_requires_python == requires_python(pip_wheel)
    assert expected_requires_python == requires_python(pip_distribution)


def test_requires_python_none(pygoogleearth_zip_sdist):
    # type: (str) -> None
    assert requires_python(pygoogleearth_zip_sdist) is None
    with example_distribution("aws_cfn_bootstrap-1.4-py2-none-any.whl") as (wheel_path, dist):
        assert requires_python(wheel_path) is None
        assert requires_python(dist) is None


def test_requires_dists():
    # type: () -> None
    with example_distribution("aws_cfn_bootstrap-1.4-py2-none-any.whl") as (wheel_path, dist):
        expected_requirements = [
            Requirement.parse(req)
            for req in ("python-daemon>=1.5.2,<2.0", "pystache>=0.4.0", "setuptools")
        ]
        assert expected_requirements == list(requires_dists(wheel_path))
        assert expected_requirements == list(requires_dists(dist))


def test_requires_dists_none(pygoogleearth_zip_sdist):
    # type: (str) -> None
    assert [] == list(requires_dists(pygoogleearth_zip_sdist))
    with example_distribution("MarkupSafe-1.0-cp27-cp27mu-linux_x86_64.whl") as (wheel_path, dist):
        assert [] == list(requires_dists(wheel_path))
        assert [] == list(requires_dists(dist))

    # This tests a strange case detailed here:
    #   https://github.com/pantsbuild/pex/issues/1201#issuecomment-791715585
    with downloaded_sdist("et-xmlfile==1.0.1") as sdist, warnings.catch_warnings(
        record=True
    ) as events:
        assert [] == list(requires_dists(sdist))
        assert len(events) == 1
        warning = events[0]
        assert PEXWarning == warning.category
        assert (
            dedent(
                """\
                Ignoring 1 `Requires` field in {sdist} metadata:
                1.) Requires: python (>=2.6.0)

                You may have issues using the 'et_xmlfile' distribution as a result.
                More information on this workaround can be found here:
                  https://github.com/pantsbuild/pex/issues/1201#issuecomment-791715585
                """
            ).format(sdist=sdist)
            == str(warning.message)
        )


def test_wheel_metadata_project_name_fuzzy_issues_1375():
    # type: () -> None
    with example_distribution("PyAthena-1.9.0-py2.py3-none-any.whl") as (wheel_path, dist):
        expected = ProjectNameAndVersion("PyAthena", "1.9.0")
        assert expected == project_name_and_version(wheel_path)
        assert expected == project_name_and_version(dist)

    with example_distribution("PyAthena-1.11.5-py2.py3-none-any.whl") as (wheel_path, dist):
        expected = ProjectNameAndVersion("pyathena", "1.11.5")
        assert expected == project_name_and_version(wheel_path)
        assert expected == project_name_and_version(dist)


def test_find_dist_info_file():
    # type: () -> None
    assert (
        find_dist_info_file(
            project_name="foo",
            version="1.0",
            filename="bar",
            listing=[],
        )
        is None
    )

    assert (
        find_dist_info_file(
            project_name="foo",
            version="1.0",
            filename="bar",
            listing=[
                "foo-1.0.dist-info/baz",
            ],
        )
        is None
    )

    assert "Foo-1.0.dist-info/bar" == find_dist_info_file(
        project_name="foo",
        version="1.0",
        filename="bar",
        listing=[
            "foo-100.dist-info/bar",
            "Foo-1.0.dist-info/bar",
            "foo-1.0.dist-info/bar",
        ],
    )

    assert "stress__-.-__Test-1.0rc0.dist-info/direct_url.json" == find_dist_info_file(
        project_name="Stress-.__Test",
        version="1.0rc0",
        filename="direct_url.json",
        listing=[
            "direct_url.json",
            "foo-1.0rc0.dist-info/direct_url.json",
            "stress__-.-__Test-1.0rc0.dist-info/direct_url.json",
        ],
    )
