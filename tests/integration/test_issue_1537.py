# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import shutil

from pex.pip.version import PipVersion
from testing import run_pex_command, subprocess
from testing.mitmproxy import Proxy
from testing.pytest_utils.tmp import Tempdir


def test_rel_cert_path(
    proxy,  # type: Proxy
    tmpdir,  # type: Tempdir
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    pex_file = tmpdir.join("pex")

    workdir = tmpdir.join("workdir")
    os.mkdir(workdir)

    if PipVersion.DEFAULT is not PipVersion.VENDORED:
        # Bootstrap the non-vendored Pip outside proxy strictures.
        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "ansicolors",
                "--",
                "-c",
                "import colors",
            ],
            cwd=workdir,
        ).assert_success()

    with proxy.run() as (port, ca_cert):
        shutil.copy(ca_cert, os.path.join(workdir, "cert"))
        run_pex_command(
            args=[
                "--proxy",
                "http://localhost:{port}".format(port=port),
                "--cert",
                "cert",
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                # N.B.: The original issue (https://github.com/pex-tool/pex/issues/1537) involved
                # avro-python3 1.10.0, but that distribution utilizes setup_requires which leads to
                # issues in CI for Mac. We use the Python 2/3 version of the same distribution
                # instead, which had setup_requires removed in
                # https://github.com/apache/avro/pull/818.
                "avro==1.10.0",
                "-o",
                pex_file,
            ],
            cwd=workdir,
        ).assert_success()
        subprocess.check_call(args=[pex_file, "-c", "import avro"])
