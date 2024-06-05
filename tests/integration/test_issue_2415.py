# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import atexit
import os.path
import re
import subprocess
import sys
import threading
from textwrap import dedent
from threading import Event
from typing import Optional

import pytest

from pex.common import safe_open
from pex.fetcher import URLFetcher
from pex.typing import TYPE_CHECKING
from testing import PY_VER, data, run_pex_command, IS_PYPY

if TYPE_CHECKING:
    from typing import Any

    import attr  # vendor:skip
else:
    from pex.third_party import attr


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

    @attr.s
    class LogScanner(object):
        port_seen = attr.ib(factory=Event, init=False)  # type: Event
        _port = attr.ib(default=None)  # type: Optional[int]

        def scan_log(self):
            # type: () -> None

            with open(log) as log_fp:
                for line in log_fp:
                    if self._port is None:
                        match = re.search(r"Listening at: http://127.0.0.1:(?P<port>\d{1,5})", line)
                        if match:
                            self._port = int(match.group("port"))
                            self.port_seen.set()

        @property
        def port(self):
            # type: () -> int
            self.port_seen.wait()
            assert self._port is not None
            return self._port

    log_scanner = LogScanner()
    log_scan_thread = threading.Thread(target=log_scanner.scan_log)
    log_scan_thread.daemon = True
    log_scan_thread.start()

    with open(os.path.join(str(tmpdir), "stderr"), "wb+") as stderr_fp:
        gunicorn = subprocess.Popen(
            args=[pex, "--bind", "127.0.0.1:0", "--log-file", log], stderr=stderr_fp
        )
        atexit.register(gunicorn.kill)

        with URLFetcher().get_body_stream(
            "http://127.0.0.1:{port}".format(port=log_scanner.port)
        ) as http_fp:
            assert b"Hello, World!" == http_fp.read().strip()

        gunicorn.kill()
        log_scan_thread.join()
        stderr_fp.flush()
        stderr_fp.seek(0)
        stderr = stderr_fp.read()
        assert b"MonkeyPatchWarning: Monkey-patching ssl after ssl " not in stderr, stderr.decode(
            "utf-8"
        )
