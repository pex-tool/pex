# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import shutil
import subprocess

from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.mitmproxy import Proxy

if TYPE_CHECKING:
    from typing import Any


def test_rel_cert_path(
    proxy,  # type: Proxy
    tmpdir,  # type: Any
):
    # type: (...) -> None
    pex_file = os.path.join(str(tmpdir), "pex")
    workdir = os.path.join(str(tmpdir), "workdir")
    os.mkdir(workdir)
    with proxy.run() as (port, ca_cert):
        shutil.copy(ca_cert, os.path.join(workdir, "cert"))
        run_pex_command(
            args=[
                "--proxy",
                "http://localhost:{port}".format(port=port),
                "--cert",
                "cert",
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
