# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import atexit
import os.path
import re
import subprocess
from textwrap import dedent
from typing import Optional

import pytest

from pex.common import safe_open
from pex.fetcher import URLFetcher
from pex.typing import TYPE_CHECKING
from testing import IS_PYPY, PY_VER, data, run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    IS_PYPY or PY_VER < (3, 8) or PY_VER >= (3, 13),
    reason=(
        "The lock file for this test only supports CPythons >=3.8,<3.13 which were the officially "
        "supported CPythons at the time issue 2415 was reported."
    ),
)
def test_gevent_monkeypatch(tmpdir):
    # type: (Any) -> None

    with safe_open(os.path.join(str(tmpdir), "app.py"), "w") as app_fp:
        app_fp.write(
            dedent(
                """\
                from gevent import monkey
                monkey.patch_all()

                from flask import Flask


                app = Flask(__name__)


                @app.route("/")
                def hello_world():
                    return "Hello, World!"
                """
            )
        )

    pex_root = os.path.join(str(tmpdir), "pex_root")
    pex = os.path.join(str(tmpdir), "pex")

    # N.B.: Created with the following, where gevent 1.3.4 was picked as a lower bound since it
    # 1st introduced the `from gevent import monkey; monkey.patch_all()` ssl check warning that is
    # the subject of issue 2415:
    #
    # pex3 lock create \
    #   --resolver-version pip-2020-resolver \
    #   --pip-version latest \
    #   --style universal \
    #   --interpreter-constraint ">=3.8,<3.13" \
    #   --indent 2 \
    #   flask \
    #   "gevent>=1.3.4" \
    #   gunicorn
    lock = data.path("locks", "issue-2415.lock.json")

    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--lock",
            lock,
            "-M",
            "app",
            "-c",
            "gunicorn",
            "--inject-args",
            "app:app",
            "-o",
            pex,
        ],
        cwd=str(tmpdir),
    ).assert_success()

    log = os.path.join(str(tmpdir), "log")
    os.mkfifo(log)

    with open(os.path.join(str(tmpdir), "stderr"), "wb+") as stderr_fp:
        gunicorn = subprocess.Popen(
            args=[pex, "--bind", "127.0.0.1:0", "--log-file", log], stderr=stderr_fp
        )
        atexit.register(gunicorn.kill)

        # N.B.: Since the fifo is blocking, we can only open it now, after the server is launched
        # in the background where it too is blocked waiting to write to the log.
        with open(log) as log_fp:
            port = None  # type: Optional[int]
            for line in log_fp:
                match = re.search(r"Listening at: http://127.0.0.1:(?P<port>\d{1,5})", line)
                if match:
                    port = int(match.group("port"))
                    break
            assert port is not None, "Failed to determine port from gunicorn log at {log}".format(
                log=log
            )

            with URLFetcher().get_body_stream(
                "http://127.0.0.1:{port}".format(port=port)
            ) as http_fp:
                assert b"Hello, World!" == http_fp.read().strip()

            gunicorn.kill()

        stderr_fp.seek(0)
        stderr = stderr_fp.read()
        assert b"MonkeyPatchWarning: Monkey-patching ssl after ssl " not in stderr, stderr.decode(
            "utf-8"
        )
