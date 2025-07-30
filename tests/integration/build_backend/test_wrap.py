# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import sys
import tarfile
from contextlib import closing
from textwrap import dedent

import pytest

from pex.build_system import pep_517
from pex.common import open_zip, safe_open
from pex.interpreter import PythonInterpreter
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.result import try_
from pex.targets import LocalInterpreter
from pex.typing import TYPE_CHECKING
from testing import WheelBuilder
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Builder(object):
    _tmpdir = attr.ib()  # type: Tempdir
    _pip_version = attr.ib()  # type: PipVersionValue

    def build_sdist(self, project_directory):
        # type: (str) -> str
        return try_(
            pep_517.build_sdist(
                project_directory=project_directory,
                dist_dir=self._tmpdir.join("dist"),
                target=LocalInterpreter.create(),
                resolver=ConfiguredResolver.version(self._pip_version),
            )
        )

    def build_wheel(self, project_directory):
        # type: (str) -> str
        return WheelBuilder(
            source_dir=project_directory,
            wheel_dir=self._tmpdir.join("dist"),
            interpreter=PythonInterpreter.get(),
            pip_version=self._pip_version,
        ).bdist()


@pytest.fixture
def builder(tmpdir):
    # type: (Tempdir) -> Builder

    # N.B.: We need modern Pip to be able to parse pyproject.toml with heterogeneous arrays.
    return Builder(tmpdir=tmpdir, pip_version=PipVersion.LATEST_COMPATIBLE)


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 8),
    reason="We need build system support for heterogeneous arrays used in pyproject.toml.",
)
def test_wrap_script_locks(
    tmpdir,  # type: Tempdir
    builder,  # type: Builder
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    project_dir = tmpdir.join("project")
    with safe_open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools", "pex @ file://{pex_project_dir}"]
                build-backend = "pex.build_backend.wrap"

                [tool.pex.build_backend]
                delegate-build-backend = "setuptools.build_meta"

                [[tool.pex.build_backend.script-locks]]
                path = "pylock.toml"

                [[tool.pex.build_backend.script-locks]]
                name = "bar"
                command = ["{{sys_executable}}", "create-lock.py", "{{lock_path}}"]

                [project]
                name = "foo"
                version = "0.1"
                """
            ).format(pex_project_dir=pex_project_dir)
        )

    with safe_open(os.path.join(project_dir, "pylock.toml"), "w") as fp:
        fp.write("Slartibartfast 42.")

    with safe_open(os.path.join(project_dir, "create-lock.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import sys


                with open(sys.argv[1], "w") as fp:
                    fp.write("Not a lock!")
                """
            )
        )

    sdist = builder.build_sdist(project_dir)
    locks = tmpdir.join("sdist")
    sdist_root_dir = "foo-0.1"
    with closing(tarfile.open(sdist)) as tf:
        tf.extract(os.path.join(sdist_root_dir, "pylock.toml"), locks)
        tf.extract(os.path.join(sdist_root_dir, "pylock.bar.toml"), locks)

    with open(os.path.join(locks, sdist_root_dir, "pylock.toml")) as fp:
        assert "Slartibartfast 42." == fp.read()

    with open(os.path.join(locks, sdist_root_dir, "pylock.bar.toml")) as fp:
        assert "Not a lock!" == fp.read()

    wheel = builder.build_wheel(project_dir)
    with open_zip(wheel) as zf:
        assert b"Slartibartfast 42." == zf.read("foo-0.1.dist-info/pylock/pylock.toml")
        assert b"Not a lock!" == zf.read("foo-0.1.dist-info/pylock/pylock.bar.toml")
