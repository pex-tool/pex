# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import os
from textwrap import dedent

from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_undeclared_setuptools_import_on_pex_path(tmpdir):
    # type: (Any) -> None
    """Test that packages which access pkg_resources at import time can be found with pkg_resources.

    See https://github.com/pantsbuild/pex/issues/729 for context. We warn when a package accesses
    pkg_resources without declaring it in install_requires, but we also want to check that those
    packages can be accessed successfully via the PEX_PATH.
    """
    setuptools_pex = os.path.join(str(tmpdir), "setuptools.pex")
    # NB: the specific setuptools version does not necessarily matter. We only pin the version to
    # avoid a future version of setuptools potentially fixing this issue and then us no longer
    # checking that Pex is behaving properly for older setuptools versions.
    run_pex_command(["setuptools==40.6.3", "-o", setuptools_pex]).assert_success()

    # We constrain google-crc32c to avoid compilation errors in CI for PyPy which has no published
    # wheels.
    #
    # Via google-resumable-media>=0.3.1 which nets 2.0.0, via google-crc32c>=0.3.1 which nets 1.1.3
    # which fails to compile with:
    #
    # gcc -pthread -DNDEBUG -O2 -fPIC -I/opt/hostedtoolcache/PyPy/3.6.12/x64/include -c src/google_crc32c/_crc32c.c -o build/temp.linux-x86_64-3.6/src/google_crc32c/_crc32c.o
    # src/google_crc32c/_crc32c.c:3:10: fatal error: crc32c/crc32c.h: No such file or directory
    #     3 | #include <crc32c/crc32c.h>
    #       |          ^~~~~~~~~~~~~~~~~
    # compilation terminated.
    constraints = os.path.join(str(tmpdir), "constraints.txt")
    with open(constraints, "w") as fp:
        print("google-crc32c==1.1.2", file=fp)
        print("protobuf<=3.17.3", file=fp)

    bigquery_pex = os.path.join(str(tmpdir), "bigquery.pex")
    run_pex_command(
        args=["google-cloud-bigquery==1.10.0", "--constraints", constraints, "-o", bigquery_pex]
    ).assert_success()

    src_dir = os.path.join(str(tmpdir), "src")
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
