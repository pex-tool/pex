# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import hashlib
import os.path
import re
import shutil
import sys
from textwrap import dedent

import pytest

from pex import targets, toml
from pex.common import safe_mkdir, safe_open
from pex.dist_metadata import DistMetadata, Requirement
from pex.orderedset import OrderedSet
from pex.resolve.lockfile.pep_751 import Pylock
from pex.result import try_
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper
from testing import IntegResults, WheelBuilder, run_pex_command
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Any, Dict, Iterable, Mapping, Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class WheelInfo(object):
    file = attr.ib()  # type: str
    marker = attr.ib(default=None)  # type: Optional[str]
    dependencies = attr.ib(default=())  # type: Iterable[Mapping[str, Any]]


def create_lock_file(
    tmpdir,  # type: Tempdir
    *wheels  # type: WheelInfo
):
    # type: (...) -> str

    def create_package(wheel):
        # type: (WheelInfo) -> Dict[str, Any]
        dist_metadata = DistMetadata.load(wheel.file)
        package = {
            "name": dist_metadata.project_name.normalized,
            "version": dist_metadata.version.normalized,
        }  # type: Dict[str, Any]
        if wheel.marker:
            package["marker"] = wheel.marker
        package["dependencies"] = list(wheel.dependencies)
        package["wheels"] = [
            {
                "path": wheel.file,
                "hashes": {"sha256": CacheHelper.hash(wheel.file, hasher=hashlib.sha256)},
            }
        ]
        return package

    pylock_toml = tmpdir.join("pylock.toml")
    with open(pylock_toml, "wb") as fp:
        toml.dump(
            data={
                "lock-version": "1.0",
                "requires-python": ">=2.7",
                "created-by": __name__,
                "packages": [create_package(wheel) for wheel in wheels],
            },
            output=fp,
        )
    return pylock_toml


def create_lock(
    tmpdir,  # type: Tempdir
    *wheels  # type: WheelInfo
):
    # type: (...) -> Pylock
    return try_(Pylock.parse(create_lock_file(tmpdir, *wheels)))


def create_wheel(
    wheels_dir,  # type: str
    projects_dir,  # type: str
    project_name,  # type: str
    version,  # type: str
    dependencies=(),  # type: Iterable[str]
):
    # type: (...) -> str

    project_dir = os.path.join(
        projects_dir, "{project_name}-{version}".format(project_name=project_name, version=version)
    )
    wheel_builder = WheelBuilder(source_dir=project_dir)

    with safe_open(os.path.join(project_dir, "{name}.py".format(name=project_name)), "w") as fp:
        for name in OrderedSet(Requirement.parse(dep).name for dep in dependencies):
            print("import", name, file=fp)
        print("print('{name} {version}')".format(name=project_name, version=version), file=fp)
    with safe_open(os.path.join(project_dir, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = {name}
                version = {version}

                [options]
                py_modules = {name}
                """.format(
                    name=project_name, version=version
                )
            )
        )
        if dependencies:
            print("install_requires =", file=fp)
            for dependency in dependencies:
                print("    ", dependency, sep="", file=fp)

    with safe_open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools"]
                backend = ["setuptools.build_meta"]
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup


                setup()
                """
            )
        )

    wheel_file = wheel_builder.bdist()
    dst = os.path.join(wheels_dir, os.path.basename(wheel_file))
    shutil.move(wheel_file, dst)
    return dst


@pytest.fixture
def projects_dir(tmpdir):
    # type: (Tempdir) -> str
    return safe_mkdir(tmpdir.join("projects"))


@pytest.fixture
def wheels_dir(tmpdir):
    # type: (Tempdir) -> str
    return safe_mkdir(tmpdir.join("wheels"))


CURRENT_INTERPRETER_VERSION = "{major}.{minor}".format(
    major=sys.version_info[0], minor=sys.version_info[1]
)
B1_DEP_MARKER = "python_version == '{version}'".format(version=CURRENT_INTERPRETER_VERSION)
B2_DEP_MARKER = "python_version != '{version}'".format(version=CURRENT_INTERPRETER_VERSION)


@pytest.fixture
def wheel_a1(
    tmpdir,  # type: Tempdir
    projects_dir,  # type: str
    wheels_dir,  # type: str
):
    # type: (...) -> str
    return create_wheel(
        wheels_dir=wheels_dir,
        projects_dir=projects_dir,
        project_name="a",
        version="1",
        dependencies=[
            "b==1; {marker}".format(marker=B1_DEP_MARKER),
            "b>1; {marker}".format(marker=B2_DEP_MARKER),
        ],
    )


@pytest.fixture
def wheel_b1(
    tmpdir,  # type: Tempdir
    projects_dir,  # type: str
    wheels_dir,  # type: str
):
    # type: (...) -> WheelInfo
    return WheelInfo(
        file=create_wheel(
            wheels_dir=wheels_dir, projects_dir=projects_dir, project_name="b", version="1"
        ),
        marker=B1_DEP_MARKER,
    )


@pytest.fixture
def wheel_b2(
    tmpdir,  # type: Tempdir
    projects_dir,  # type: str
    wheels_dir,  # type: str
):
    # type: (...) -> WheelInfo
    return WheelInfo(
        file=create_wheel(
            wheels_dir=wheels_dir, projects_dir=projects_dir, project_name="b", version="2"
        ),
        marker=B2_DEP_MARKER,
    )


def pex_from_lock(lock):
    # type: (str) -> IntegResults
    return run_pex_command(args=["--pylock", lock, "--", "-c", "import a"], quiet=True)


def assert_pex_from_lock(lock):
    # type: (Pylock) -> None
    pex_from_lock(lock.source).assert_success(
        expected_output_re=re.escape(os.linesep.join(("b 1", "a 1")))
    )


def test_dependencies_minimal_non_spec_compliant(
    tmpdir,  # type: Tempdir
    wheel_a1,  # type: str
    wheel_b1,  # type: WheelInfo
    wheel_b2,  # type: WheelInfo
):
    # type: (...) -> None

    lock = create_lock(
        tmpdir, WheelInfo(wheel_a1, dependencies=[{"name": "b"}]), wheel_b1, wheel_b2
    )
    assert_pex_from_lock(lock)


def test_dependencies_nominal_spec_compliant(
    tmpdir,  # type: Tempdir
    wheel_a1,  # type: str
    wheel_b1,  # type: WheelInfo
    wheel_b2,  # type: WheelInfo
):
    # type: (...) -> None

    lock = create_lock(
        tmpdir,
        WheelInfo(
            wheel_a1,
            dependencies=[{"name": "b", "version": "1"}, {"name": "b", "version": "2"}],
        ),
        wheel_b1,
        wheel_b2,
    )
    assert_pex_from_lock(lock)


def test_dependencies_strange_spec_compliant(
    tmpdir,  # type: Tempdir
    wheel_a1,  # type: str
    wheel_b1,  # type: WheelInfo
    wheel_b2,  # type: WheelInfo
):
    # type: (...) -> None

    lock = create_lock(
        tmpdir,
        WheelInfo(wheel_a1, marker=B1_DEP_MARKER, dependencies=[{"name": "b", "version": "1"}]),
        WheelInfo(wheel_a1, marker=B2_DEP_MARKER, dependencies=[{"name": "b", "version": "2"}]),
        wheel_b1,
        wheel_b2,
    )
    assert_pex_from_lock(lock)


def test_dependencies_nominal_lock_not_spec_compliant_ambiguous_install(
    tmpdir,  # type: Tempdir
    wheel_a1,  # type: str
    wheel_b1,  # type: WheelInfo
    wheel_b2,  # type: WheelInfo
):
    # type: (...) -> None

    lock = create_lock(
        tmpdir,
        WheelInfo(
            wheel_a1,
            dependencies=[{"name": "b", "version": "1"}, {"name": "b", "version": "2"}],
        ),
        wheel_b1,
        # N.B.: Now we have 2 b dependencies with a marker that evaluates to True for the current
        # interpreter, which violates the ambiguity constraint in step 5 here:
        #   https://packaging.python.org/en/latest/specifications/pylock-toml/#installation
        attr.evolve(wheel_b2, marker=B1_DEP_MARKER),
    )
    pex_from_lock(lock.source).assert_failure(
        expected_error_re=re.escape(
            "Failed to resolve compatible artifacts from lock {lock_file} created by {creator} for "
            "1 target:\n"
            "1. {target}: Found more than one match for the following projects in {lock_file}.\n"
            "+ b:\n"
            "  b 1 wheel\n"
            "  b 2 wheel\n"
            "Pex resolves must produce a unique package per project.".format(
                lock_file=lock.source, creator=lock.created_by, target=targets.current()
            )
        )
    )


def test_dependencies_nominal_lock_spec_compliant_missing_dep_name(
    tmpdir,  # type: Tempdir
    wheel_a1,  # type: str
    wheel_b1,  # type: WheelInfo
    wheel_b2,  # type: WheelInfo
):
    # type: (...) -> None

    lock_file = create_lock_file(
        tmpdir,
        WheelInfo(
            wheel_a1,
            # Although version=2 is enough to uniquely identify b2 in the lock (the only version
            # 2 package), it is not enough for Pex.
            dependencies=[{"version": "2"}],
        ),
        wheel_b1,
        wheel_b2,
    )
    pex_from_lock(lock_file).assert_failure(
        expected_error_re=re.escape(
            "Failed to parse the PEP-751 lock at {lock_file}. Error parsing content at "
            'packages[0]{{name = "a"}}.dependencies[0].\n'
            'A value for packages[0]{{name = "a"}}.dependencies[0].name is required.\n'
            "Pex requires dependency tables specify at least a `name`.\n"
            "The pylock.toml spec does not require this however.\n"
            "To subset locks created by {creator}, either they will need to add names for their "
            "dependencies or Pex will need to support more sophisticated dependency parsing.\n"
            "For more information, see the comments starting here: "
            "https://github.com/pex-tool/pex/issues/2885#issuecomment-3263138568".format(
                lock_file=lock_file, creator=__name__
            )
        )
    )
