# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from textwrap import dedent

from pex.common import safe_open, temporary_dir
from pex.testing import PY27, PY310, ensure_python_interpreter, make_env, run_pex_command


def test_top_level_requirements_requires_python_env_markers():
    # type: () -> None
    python27 = ensure_python_interpreter(PY27)
    python310 = ensure_python_interpreter(PY310)
    with temporary_dir() as td:
        src_dir = os.path.join(td, "src")
        with safe_open(os.path.join(src_dir, "test_issues_898.py"), "w") as fp:
            fp.write(
                dedent(
                    """
                    import zipp

                    print(zipp.__file__)
                    """
                )
            )

        pex_file = os.path.join(td, "zipp.pex")

        results = run_pex_command(
            args=[
                "--python={}".format(python27),
                "--python={}".format(python310),
                "zipp>=1,<=3.1.0",
                "--sources-directory={}".format(src_dir),
                "--entry-point=test_issues_898",
                "-o",
                pex_file,
            ],
        )
        results.assert_success()

        pex_root = os.path.realpath(os.path.join(td, "pex_root"))
        for python in python27, python310:
            output = subprocess.check_output([python, pex_file], env=make_env(PEX_ROOT=pex_root))
            zipp_location = os.path.realpath(output.decode("utf-8").strip())
            assert zipp_location.startswith(
                pex_root
            ), "Failed to import zipp from {} under {}".format(pex_file, python)
