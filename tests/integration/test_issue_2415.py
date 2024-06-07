# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import atexit
import os.path
import subprocess
import time
from textwrap import dedent

import pytest

from pex.common import safe_mkdir, safe_open
from pex.fetcher import URLFetcher
from pex.typing import TYPE_CHECKING
from testing import IS_MAC, IS_PYPY, PY_VER, data, run_pex_command

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
                from flask import Flask


                app = Flask(__name__)


                @app.route("/<username>")
                def hello_world(username):
                    return "Hello, {}!".format(username)
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
    #   --no-build \
    #   --indent 2 \
    #   flask \
    #   "gevent>=1.3.4" \
    #   gunicorn[gevent]
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
            "--worker-class gevent app:app",
            "-o",
            pex,
        ],
        cwd=str(tmpdir),
    ).assert_success()

    socket = os.path.join(
        safe_mkdir(os.path.expanduser("~/Library/Caches/TemporaryItems"))
        if IS_MAC
        else str(tmpdir),
        "gunicorn.sock",
    )
    with open(os.path.join(str(tmpdir), "stderr"), "wb+") as stderr_fp:
        gunicorn = subprocess.Popen(
            args=[pex, "--bind", "unix:{socket}".format(socket=socket)], stderr=stderr_fp
        )
        atexit.register(gunicorn.kill)

        start = time.time()
        while not os.path.exists(socket):
            if time.time() - start > 60:
                break
            # Local testing on an unloaded system shows gunicorn takes about a second to start up.
            time.sleep(1.0)
        assert os.path.exists(socket), (
            "Timed out after waiting {time:.3f}s for gunicorn to start and open a unix socket at "
            "{socket}".format(time=time.time() - start, socket=socket)
        )
        print(
            "Waited {time:.3f}s for gunicorn to start and open a unix socket at {socket}".format(
                time=time.time() - start, socket=socket
            )
        )

        with URLFetcher().get_body_stream("unix://{socket}/World".format(socket=socket)) as http_fp:
            assert b"Hello, World!" == http_fp.read().strip()
        gunicorn.kill()

        stderr_fp.seek(0)
        stderr = stderr_fp.read()
        assert b"MonkeyPatchWarning: Monkey-patching ssl after ssl " not in stderr, stderr.decode(
            "utf-8"
        )
