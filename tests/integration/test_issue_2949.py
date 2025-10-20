# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
from textwrap import dedent

from pex.cache.dirs import InstalledWheelDir
from pex.common import safe_open
from pex.fs import safe_symlink
from pex.pep_503 import ProjectName
from pex.pex_info import PexInfo
from pex.version import __version__
from testing import run_pex_command
from testing.docker import skip_unless_docker
from testing.pytest_utils.tmp import Tempdir


@skip_unless_docker
def test_local_project_hashing_2949_case(
    tmpdir,  # type: Tempdir
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    # Just as for the original posting in #2949, Pex uses uv to run tests; so its project dir
    # contains a `.venv/` with a dangling `python` symlink when the project is mounted into a
    # docker container. This confirms that dangling symlink does not factor into the PEX build.

    assert (
        __version__
        == subprocess.check_output(
            args=[
                "docker",
                "run",
                "--rm",
                "-v",
                "{pex_project_dir}:/code".format(pex_project_dir=pex_project_dir),
                "-w",
                "/code",
                "python:3.14-slim-trixie",
                "python",
                "-m",
                "pex",
                ".",
                "-c",
                "pex",
                "--",
                "-V",
            ]
        )
        .decode("utf-8")
        .strip()
    )


def test_local_project_hashing_elides_irrelevant_files(tmpdir):
    # type:(Tempdir) -> None

    project_dir = tmpdir.join("project")
    with safe_open(os.path.join(project_dir, "example", "__init__.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import pkgutil


                def run():
                    print(pkgutil.get_data(__name__, "data.txt").decode("utf-8"))                    
                """
            )
        )
    with safe_open(os.path.join(project_dir, "example", "data.txt"), "w") as fp:
        fp.write("42")
    with safe_open(os.path.join(project_dir, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = example
                version = 0.0.1

                [options]
                packages = example
                include_package_data = True
                
                [options.entry_points]
                console_scripts =
                    run = example:run
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write("from setuptools import setup; setup()")
    with safe_open(os.path.join(project_dir, "MANIFEST.in"), "w") as fp:
        fp.write("include example/data.txt")

    pex_root = tmpdir.join("pex-root")

    def build_pex(pex):
        # type: (str) -> str
        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                project_dir,
                "-c",
                "run",
                "-o",
                pex,
            ]
        ).assert_success()
        return pex

    def assert_built_wheels(expected_count):
        assert expected_count == len(
            list(
                installed_wheel_dir
                for installed_wheel_dir in InstalledWheelDir.iter_all(pex_root=pex_root)
                if installed_wheel_dir.project_name == ProjectName("example")
            )
        )

    pex1 = build_pex(tmpdir.join("pex1"))
    assert "42" == subprocess.check_output(args=[pex1]).decode("utf-8").strip()
    assert_built_wheels(1)
    wheel1, fingerprint1 = PexInfo.from_pex(pex1).distributions.popitem()

    with safe_open(os.path.join(project_dir, "example", "data.txt"), "w") as fp:
        fp.write("37")
    pex2 = build_pex(tmpdir.join("pex2"))
    assert "37" == subprocess.check_output(args=[pex2]).decode("utf-8").strip()
    assert_built_wheels(2)
    wheel2, fingerprint2 = PexInfo.from_pex(pex2).distributions.popitem()
    assert wheel1 == wheel2
    assert fingerprint1 != fingerprint2

    safe_symlink(
        os.path.join(project_dir, "does-not-exist"), os.path.join(project_dir, "dangling-symlink")
    )
    pex3 = build_pex(tmpdir.join("pex3"))
    assert "37" == subprocess.check_output(args=[pex3]).decode("utf-8").strip()
    assert_built_wheels(2)
    wheel3, fingerprint3 = PexInfo.from_pex(pex3).distributions.popitem()
    assert wheel2 == wheel3
    assert fingerprint2 == fingerprint3
