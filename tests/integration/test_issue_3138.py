# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os.path
import subprocess
import sys
from textwrap import dedent

import pytest
from colors import colors

from pex.common import safe_open
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.lockfile.pep_751 import Pylock
from pex.result import try_
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(
    sys.version_info < (3, 8),
    reason="The test uses uv to export a pylock.toml and uv only works against Python >=3.8.",
)
def test_uv_editable_deps_pylock(tmpdir):
    # type: (Tempdir) -> None

    workspace = tmpdir.join("project")
    requires_python = "=={major}.{minor}.*".format(
        major=sys.version_info[0], minor=sys.version_info[1]
    )

    project_a = os.path.join(workspace, "a")
    with safe_open(os.path.join(project_a, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [project]
                name = "a"
                version = "0.1.0"
                requires-python = "{requires_python}"
                dependencies = []

                [build-system]
                requires = ["uv_build>=0.11.2,<0.12.0"]
                build-backend = "uv_build"
                """
            ).format(requires_python=requires_python)
        )
    with safe_open(os.path.join(project_a, "src", "a", "__init__.py"), "w") as fp:
        print("MEANING_OF_LIFE=42", file=fp)

    project_b = os.path.join(workspace, "b")
    with safe_open(os.path.join(project_b, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [project]
                name = "b"
                version = "0.1.0"
                requires-python = "{requires_python}"
                dependencies = [
                    "ansicolors==1.1.8",
                    "a"
                ]

                [tool.uv.sources]
                a = {{ path = "../a", editable = true }}

                [build-system]
                requires = ["uv_build>=0.11.2,<0.12.0"]
                build-backend = "uv_build"

                [project.scripts]
                hello = "b:main"
                """
            ).format(requires_python=requires_python)
        )
    with safe_open(os.path.join(project_b, "src", "b", "__init__.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import colors
                from a import MEANING_OF_LIFE


                def main():
                    print("The answer to the question:", colors.green(MEANING_OF_LIFE))
                """
            )
        )

    subprocess.check_call(
        args=[
            "uv",
            "--directory",
            os.path.relpath(project_b, workspace),
            "--quiet",
            "export",
            "--format",
            "pylock.toml",
            "--output-file",
            "pylock.toml",
            "--no-dev",
        ],
        cwd=workspace,
    )
    pylock_toml = os.path.join(project_b, "pylock.toml")
    pylock = try_(Pylock.parse(pylock_toml))
    assert {
        ProjectName("ansicolors"): Version("1.1.8"),
        ProjectName("a"): None,
        ProjectName("b"): None,
    } == {package.project_name: package.version for package in pylock.packages}

    pex_root = tmpdir.join("pex-root")
    pex_b = tmpdir.join("b.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--pylock",
            os.path.relpath(pylock_toml, workspace),
            "-o",
            pex_b,
            "-c",
            "hello",
        ],
        cwd=workspace,
    ).assert_success()

    assert (
        "The answer to the question: {answer}".format(answer=colors.green(42))
        == subprocess.check_output(args=[pex_b]).decode("utf-8").strip()
    )
