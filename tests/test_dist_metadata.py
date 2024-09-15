# Copyright 2020 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
import re
import tarfile
import warnings
from contextlib import contextmanager
from textwrap import dedent

import pytest

from pex.common import open_zip, safe_open, temporary_dir, touch
from pex.dist_metadata import (
    Distribution,
    InvalidMetadataError,
    MetadataError,
    MetadataType,
    ProjectNameAndVersion,
    Requirement,
    project_name_and_version,
    requires_dists,
    requires_python,
)
from pex.pep_427 import install_wheel_chroot
from pex.pep_503 import ProjectName
from pex.pex_warnings import PEXWarning
from pex.pip.installation import get_pip
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.resolver_configuration import BuildConfiguration
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING
from testing import PY_VER
from testing.dist_metadata import create_dist_metadata

if TYPE_CHECKING:
    from typing import Any, Iterator, Tuple


@contextmanager
def installed_wheel(wheel_path):
    # type: (str) -> Iterator[Distribution]
    with temporary_dir() as install_dir:
        install_wheel_chroot(wheel_path=wheel_path, destination=install_dir)
        yield Distribution.load(install_dir)


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
        get_pip(resolver=ConfiguredResolver.default()).spawn_download_distributions(
            download_dir=download_dir,
            requirements=[requirement],
            transitive=False,
            build_configuration=BuildConfiguration.create(allow_wheels=False),
        ).wait()
        dists = os.listdir(download_dir)
        assert len(dists) == 1, "Expected 1 dist to be downloaded for {}.".format(requirement)
        sdist = os.path.join(download_dir, dists[0])
        assert sdist.endswith((".tar.gz", ".zip"))
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


PIP_PROJECT_NAME_AND_VERSION = ProjectNameAndVersion("pip", "9.0.1")


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
        get_pip(resolver=ConfiguredResolver.default()).spawn_build_wheels(
            [pip_tgz_sdist], wheel_dir=wheel_dir
        ).wait()
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
    ) == ProjectNameAndVersion.from_filename("a-distribution-name-1.2.3.tar.gz")


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

    assert project_name_and_version(sdist_path, fallback_to_filename=False) is None
    assert ProjectNameAndVersion("bar-baz", "4.5.6") == project_name_and_version(
        sdist_path, fallback_to_filename=True
    )

    name_and_version = "eggs-7.8.9"
    pkf_info_path = "{}/PKG-INFO".format(name_and_version)

    def write_sdist_tgz(extension):
        # type: (str) -> str
        sdist_path = tmp_path("{}.{}".format(name_and_version, extension))
        with tarfile.open(sdist_path, mode="w:gz") as tf:
            tf.add(pkg_info_src, arcname=pkf_info_path)
        return sdist_path

    assert expected_metadata_project_name_and_version == project_name_and_version(
        write_sdist_tgz("tar.gz"), fallback_to_filename=False
    )
    assert expected_metadata_project_name_and_version == project_name_and_version(
        write_sdist_tgz("tgz"), fallback_to_filename=False
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
    expected_requires_python = SpecifierSet(">=2.6,!=3.0.*,!=3.1.*,!=3.2.*")
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
    #   https://github.com/pex-tool/pex/issues/1201#issuecomment-791715585
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

                You may have issues using the 'et-xmlfile' distribution as a result.
                More information on this workaround can be found here:
                  https://github.com/pex-tool/pex/issues/1201#issuecomment-791715585
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


@pytest.mark.parametrize(
    "metadata_type",
    [
        pytest.param(metadata_type, id=str(metadata_type))
        for metadata_type in (MetadataType.DIST_INFO, MetadataType.EGG_INFO)
    ],
)
def test_find_dist_info_file(
    tmpdir,  # type: Any
    metadata_type,  # type: MetadataType.Value
):
    # type: (...) -> None
    assert (
        metadata_type.load_metadata(location=str(tmpdir), project_name=ProjectName("foo")) is None
    )

    def metadata_dir_name(project_name_and_version):
        # type: (str) -> str
        return "{project_name_and_version}.{metadata_type}".format(
            project_name_and_version=project_name_and_version,
            metadata_type="dist-info" if metadata_type is MetadataType.DIST_INFO else "egg-info",
        )

    metadata_file_name = "METADATA" if metadata_type is MetadataType.DIST_INFO else "PKG-INFO"

    touch(os.path.join(str(tmpdir), metadata_dir_name("foo-1.0"), "baz"))
    assert (
        metadata_type.load_metadata(location=str(tmpdir), project_name=ProjectName("foo")) is None
    )

    touch(os.path.join(str(tmpdir), metadata_dir_name("foo-1.0"), metadata_file_name))
    assert (
        metadata_type.load_metadata(location=str(tmpdir), project_name=ProjectName("foo")) is None
    )

    def write_pkg_info_file(
        location,  # type: str
        name,  # type: str
        version,  # type: str
    ):
        # type: (...) -> None
        with safe_open(
            os.path.join(
                location,
                metadata_dir_name("{name}-{version}".format(name=name, version=version)),
                metadata_file_name,
            ),
            "w",
        ) as fp:
            print("Metadata-Version: 1.0", file=fp)
            print("Name: {name}".format(name=name), file=fp)
            print("Version: {version}".format(version=version), file=fp)

    foo_location = os.path.join(str(tmpdir), "foo_location")
    touch(os.path.join(foo_location, metadata_dir_name("foo-100"), "bar"))
    expected_metadata_relpath = os.path.join(metadata_dir_name("Foo-1.0"), "bar")
    touch(os.path.join(foo_location, expected_metadata_relpath))
    write_pkg_info_file(foo_location, name="Foo", version="1.0")

    metadata_files = metadata_type.load_metadata(
        location=foo_location, project_name=ProjectName("foo")
    )
    assert metadata_files is not None
    assert expected_metadata_relpath == metadata_files.metadata_file_rel_path("bar")

    stress_location = os.path.join(str(tmpdir), "stress_location")
    touch(os.path.join(stress_location, "direct_url.json"))
    touch(os.path.join(stress_location, metadata_dir_name("foo-1.0rc0"), "direct_url.json"))
    expected_metadata_relpath = os.path.join(
        metadata_dir_name("stress__-.-__Test-1.0rc0"), "direct_url.json"
    )
    touch(os.path.join(stress_location, expected_metadata_relpath))
    write_pkg_info_file(
        stress_location,
        name="stress__-.-__Test",
        version="1.0rc0",
    )

    metadata_files = metadata_type.load_metadata(
        location=stress_location, project_name=ProjectName("Stress-.__Test")
    )
    assert metadata_files is not None
    assert expected_metadata_relpath == metadata_files.metadata_file_rel_path("direct_url.json")


def test_requirement_contains_requirement():
    req = Requirement.parse

    assert req("foo==1") in req("foo")
    assert req("foo") not in req("foo==1")

    assert req("bar") not in req("foo")
    assert req("bar==1") not in req("foo==1")

    assert req("foo>1,<3") not in req("foo==2")
    assert req("foo==2") in req("foo>1,<3")
    assert req("foo>=1,<3") not in req("foo>1,<3")
    assert req("foo>1,<=2") in req("foo>1,<3")


def test_invalid_metadata_requires_python_error():
    with pytest.raises(
        InvalidMetadataError,
        match=re.escape(
            "Invalid Requires-Python metadata found in foo 0.1 metadata from "
            "foo-0.1.0.dist-info/METADATA at /right/here 'not a valid specifier': "
            "Invalid specifier: 'not a valid specifier'"
        ),
    ):
        create_dist_metadata(
            project_name="foo",
            version="0.1.0",
            requires_python="not a valid specifier",
            location="/right/here",
        )


@pytest.mark.skipif(
    PY_VER < (3, 7),
    reason=(
        "The vendored packaging for Python < 3.7 does not complain about use of `*` for operators "
        "other than `==` and `!=`."
    ),
)
def test_invalid_metadata_requires_dists_error_issue_2441(tmpdir):
    with pytest.raises(
        InvalidMetadataError,
        match=re.escape(
            "Found 2 invalid Requires-Dist metadata values in foo 0.1 metadata from "
            "foo-0.1.0.dist-info/METADATA at /right/here:\n"
            "1. \"scikit-learn (>=1.0.*) ; extra == 'pipelines'\": "
            ".* suffix can only be used with `==` or `!=` operators\n"
            "    scikit-learn (>=1.0.*) ; extra == 'pipelines'\n"
            "                  ~~~~~~^\n"
            "2. \"pyarrow (>=7.0.*) ; extra == 'pipelines'\": "
            ".* suffix can only be used with `==` or `!=` operators\n"
            "    pyarrow (>=7.0.*) ; extra == 'pipelines'\n"
            "             ~~~~~~^"
        ),
    ):
        create_dist_metadata(
            project_name="foo",
            version="0.1.0",
            requires_dists=(
                "cowsay<6",
                "scikit-learn (>=1.0.*) ; extra == 'pipelines'",
                "ansicolors==1.1.8",
                "pyarrow (>=7.0.*) ; extra == 'pipelines'",
            ),
            location="/right/here",
        )

    location = str(tmpdir)
    with safe_open(os.path.join(location, "foo-0.1.0.egg-info", "requires.txt"), "w") as fp:
        fp.write(
            dedent(
                """\
                cowsay<6
                ansicolors==1.1.8

                [pipelines]
                scikit-learn>=1.0.*
                pyarrow>=7.0.*
                """
            )
        )
    with pytest.raises(
        InvalidMetadataError,
        match=re.escape(
            "Found 2 invalid Requires-Dist metadata values in foo 0.1 metadata from "
            "foo-0.1.0.egg-info/PKG-INFO at {location}:\n"
            "1. foo-0.1.0.egg-info/requires.txt:5 'scikit-learn>=1.0.*; extra == \"pipelines\"': "
            ".* suffix can only be used with `==` or `!=` operators\n"
            '    scikit-learn>=1.0.*; extra == "pipelines"\n'
            "                ~~~~~~^\n"
            "2. foo-0.1.0.egg-info/requires.txt:6 'pyarrow>=7.0.*; extra == \"pipelines\"': "
            ".* suffix can only be used with `==` or `!=` operators\n"
            '    pyarrow>=7.0.*; extra == "pipelines"'
            "\n           ~~~~~~^".format(location=location)
        ),
    ):
        create_dist_metadata(
            project_name="foo",
            version="0.1.0",
            location=location,
            metadata_type=MetadataType.EGG_INFO,
        )
