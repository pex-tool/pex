# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess
from textwrap import dedent

import colors  # vendor:skip

from pex.common import safe_open
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex import PEX
from testing import run_pex_command
from testing.pytest.tmp import Tempdir


def test_pex_from_dependency_groups(tmpdir):
    # type: (Tempdir) -> None

    project_dir = tmpdir.join("project")
    with safe_open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [project]
                dependencies = [
                    "does-not-exist",
                    "requests",
                ]
                
                [dependency-groups]
                colors = ["ansicolors==1.1.8"]
                speak = ["cowsay==5.0"]
                """
            )
        )

    pex = tmpdir.join("pex")
    run_pex_command(
        args=[
            "--group",
            "colors@.",
            "--group",
            "speak@{project}".format(project=project_dir),
            "-c",
            "cowsay",
            "-o",
            pex,
        ],
        cwd=project_dir,
    ).assert_success()

    assert sorted(
        ((ProjectName("cowsay"), Version("5.0")), (ProjectName("ansicolors"), Version("1.1.8")))
    ) == [(dist.metadata.project_name, dist.metadata.version) for dist in PEX(pex).resolve()]

    assert "| {moo} |".format(moo=colors.yellow("Moo!")) in subprocess.check_output(
        args=[pex, colors.yellow("Moo!")]
    ).decode("utf-8")
