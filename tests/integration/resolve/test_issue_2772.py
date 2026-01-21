# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess
import sys
from textwrap import dedent

import pytest

from pex.compatibility import safe_commonpath
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(sys.version_info[:2] < (3, 8), reason="PyYAML 6.0.2 requires Python>=3.8.")
def test_uv_lock_export_name_normalization(tmpdir):
    # type: (Tempdir) -> None

    with open(tmpdir.join("pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [project]
                name = "fake"
                version = "1"
                requires-python = "=={major}.{minor}.*"
                dependencies = ["PyYAML==6.0.2"]
                """.format(
                    major=sys.version_info[0], minor=sys.version_info[1]
                )
            )
        )

    pylock = tmpdir.join("pylock.toml")
    subprocess.check_call(
        args=[
            "uv",
            "export",
            "--quiet",
            "--no-emit-project",
            "--format",
            "pylock.toml",
            "-o",
            pylock,
        ],
        cwd=str(tmpdir),
    )

    pex_root = tmpdir.join("pex_root")
    pyyaml_pex = tmpdir.join("pyyaml.pex")
    run_pex_command(
        args=[
            "--pylock",
            pylock,
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "-o",
            pyyaml_pex,
        ]
    ).assert_success()

    pyyaml_package_path = (
        subprocess.check_output(args=[pyyaml_pex, "-c", "import yaml; print(yaml.__file__)"])
        .decode("utf-8")
        .strip()
    )
    assert pex_root == safe_commonpath((pex_root, pyyaml_package_path))
