# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

from pex.common import temporary_dir
from pex.testing import make_env, run_pex_command, run_simple_pex


def test_pkg_resource_early_import_on_pex_path():
    # type: () -> None
    """Test that packages which access pkg_resources at import time can be found with pkg_resources.

    See https://github.com/pantsbuild/pex/issues/749 for context. We only declare namespace packages
    once all environments have been resolved including ones passed in via PEX_PATH. This avoids
    importing pkg_resources too early which is potentially impactful with packages interacting with
    pkg_resources at import time.
    """
    with temporary_dir() as td:

        six_pex = os.path.join(td, "six.pex")
        run_pex_command(["six", "-o", six_pex]).assert_success()

        src_dir = os.path.join(td, "src")
        os.mkdir(src_dir)

        src_file = os.path.join(src_dir, "execute_import.py")
        with open(src_file, "w") as fp:
            fp.write(
                dedent(
                    """\
                    import pkg_resources
                    import sys

                    pkg_resources.get_distribution('six')
                    """
                )
            )

        setuptools_pex = os.path.join(td, "autopep8.pex")
        run_pex_command(
            [
                "autopep8",
                "setuptools",
                "-D",
                src_dir,
                "--entry-point",
                "execute_import",
                "-o",
                setuptools_pex,
            ]
        ).assert_success()
        _, return_code = run_simple_pex(setuptools_pex, env=make_env(PEX_PATH=six_pex))
        assert return_code == 0
