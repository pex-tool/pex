# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

from pex.common import temporary_dir
from pex.testing import run_pex_command


def test_undeclared_setuptools_import_on_pex_path():
    # type: () -> None
    """Test that packages which access pkg_resources at import time can be found with pkg_resources.

    See https://github.com/pantsbuild/pex/issues/729 for context. We warn when a package accesses
    pkg_resources without declaring it in install_requires, but we also want to check that those
    packages can be accessed successfully via the PEX_PATH.
    """
    with temporary_dir() as td:
        setuptools_pex = os.path.join(td, "setuptools.pex")
        # NB: the specific setuptools version does not necessarily matter. We only pin the version to
        # avoid a future version of setuptools potentially fixing this issue and then us no longer
        # checking that Pex is behaving properly for older setuptools versions.
        run_pex_command(["setuptools==40.6.3", "-o", setuptools_pex]).assert_success()
        bigquery_pex = os.path.join(td, "bigquery.pex")
        run_pex_command(["google-cloud-bigquery==1.10.0", "-o", bigquery_pex]).assert_success()

        src_dir = os.path.join(td, "src")
        os.mkdir(src_dir)

        src_file = os.path.join(src_dir, "execute_import.py")
        with open(src_file, "w") as fp:
            fp.write(
                dedent(
                    """\
                    from google.cloud import bigquery

                    print('bigquery version: {}'.format(bigquery.__version__))
        """
                )
            )

        res = run_pex_command(
            [
                "--pex-path={}".format(":".join([setuptools_pex, bigquery_pex])),
                "-D",
                src_dir,
                "--entry-point",
                "execute_import",
            ]
        )
        res.assert_success()
        assert res.output.strip() == "bigquery version: 1.10.0"
