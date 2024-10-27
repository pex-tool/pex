# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os.path
from textwrap import dedent

from pex.common import safe_open, touch
from pex.compatibility import commonpath
from pex.interpreter import PythonInterpreter
from testing import run_pex_command
from testing.cli import run_pex3
from testing.pytest.tmp import Tempdir


def test_missing_download_lock_analysis_handling(
    tmpdir,  # type: Tempdir
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    my_feast = tmpdir.join("intermediary")
    touch(os.path.join(my_feast, "README.rst"))
    with safe_open(os.path.join(my_feast, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools", "wheel"]
                build-backend = "setuptools.build_meta"

                [project]
                name = "my_feast"
                version = "0.0.1"
                authors = [
                    {name = "John Sirois", email = "john.sirois@gmail.com"},
                ]
                description = "Simulates the more complex and expensive 'feast' in the issue OP."
                readme = "README.rst"
                requires-python = ">=3.7"
                license = {text = "BSD-3-Clause"}
                dependencies = [
                    "SQLAlchemy[mypy]>1,<2",
                ]
                """
            )
        )

    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--interpreter-constraint",
        "==3.10.*",
        "--style",
        "universal",
        "--resolver-version",
        "pip-2020-resolver",
        "--target-system",
        "linux",
        "--target-system",
        "mac",
        my_feast,
        "sqlalchemy==1.3.24",
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()

    pex_root = tmpdir.join("pex_root")
    result = run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--lock",
            lock,
            "sqlalchemy",
            "--",
            "-c",
            dedent(
                """\
                import json
                import sys

                import sqlalchemy


                json.dump(
                    {"version": sqlalchemy.__version__, "file": sqlalchemy.__file__},
                    sys.stdout,
                )
                """
            ),
        ],
        python=py310.binary,
    )
    result.assert_success()

    data = json.loads(result.output)
    assert "1.3.24" == data["version"]
    assert pex_root == commonpath([pex_root, data["file"]])
