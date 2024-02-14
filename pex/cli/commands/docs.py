# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import errno
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from textwrap import dedent

from pex import docs
from pex.cli.command import BuildTimeCommand
from pex.commands.command import try_open_file
from pex.common import safe_open
from pex.result import Error, Result
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from pex.version import __version__

if TYPE_CHECKING:
    from typing import Optional, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


logger = logging.getLogger(__name__)


SERVER_NAME = "Pex v{version} docs HTTP server".format(version=__version__)
SERVER_DIR = os.path.join(ENV.PEX_ROOT, "docs", "server", __version__)


@attr.s(frozen=True)
class Pidfile(object):
    _PIDFILE = os.path.join(SERVER_DIR, "pidfile")

    @classmethod
    def load(cls):
        # type: () -> Optional[Pidfile]
        try:
            with open(cls._PIDFILE) as fp:
                data = json.load(fp)
            return cls(url=data["url"], pid=data["pid"])
        except (OSError, IOError, ValueError, KeyError) as e:
            logger.warning(
                "Failed to load {server} pid file from {path}: {err}".format(
                    server=SERVER_NAME, path=cls._PIDFILE, err=e
                )
            )
            return None

    @staticmethod
    def _read_url(
        server_log,  # type: str
        timeout,  # type: float
    ):
        # type: (...) -> Optional[str]

        # The permutations of Python versions, simple http server module and the output it provides:
        #  2.7: Serving HTTP on 0.0.0.0 port 46399 ... -mSimpleHttpServer
        #  3.5: Serving HTTP on 0.0.0.0 port 45577 ... -mhttp.server
        # 3.6+: Serving HTTP on 0.0.0.0 port 33539 (http://0.0.0.0:33539/) ... -mhttp.server

        start = time.time()
        while time.time() - start < timeout:
            with open(server_log) as fp:
                for line in fp:
                    if line.endswith(os.linesep):
                        match = re.search(r"Serving HTTP on 0.0.0.0 port (?P<port>\d+)", line)
                        if match:
                            port = match.group("port")
                            return "http://localhost:{port}".format(port=port)
        return None

    @classmethod
    def record(
        cls,
        server_log,  # type: str
        pid,  # type: int
        timeout=5.0,  # type: float
    ):
        # type: (...) -> Optional[Pidfile]
        url = cls._read_url(server_log, timeout)
        if not url:
            return None

        with safe_open(cls._PIDFILE, "w") as fp:
            json.dump(dict(url=url, pid=pid), fp, indent=2, sort_keys=True)
        return cls(url=url, pid=pid)

    url = attr.ib()  # type: str
    pid = attr.ib()  # type: int

    def alive(self):
        # type: () -> bool
        # TODO(John Sirois): Handle pid rollover
        try:
            os.kill(self.pid, 0)
            return True
        except OSError as e:
            if e.errno == errno.ESRCH:  # No such process.
                return False
            raise

    def kill(self):
        # type: () -> None
        os.kill(self.pid, signal.SIGTERM)


@attr.s(frozen=True)
class LaunchResult(object):
    url = attr.ib()  # type: str
    already_running = attr.ib()  # type: bool


def launch_docs_server(
    document_root,  # type: str
    port,  # type: int
    timeout=5.0,  # type: float
):
    # type: (...) -> Union[str, LaunchResult]

    pidfile = Pidfile.load()
    if pidfile and pidfile.alive():
        return LaunchResult(url=pidfile.url, already_running=True)

    # Not proper daemonization, but good enough.
    log = os.path.join(SERVER_DIR, "log.txt")
    http_server_module = "http.server" if sys.version_info[0] == 3 else "SimpleHttpServer"
    env = os.environ.copy()
    # N.B.: We set up line buffering for the process pipes as well as the underlying Python running
    # the http server to ensure we can observe the `Serving HTTP on ...` line we need to grab the
    # ephemeral port chosen.
    env.update(PYTHONUNBUFFERED="1")
    with safe_open(log, "w") as fp:
        process = subprocess.Popen(
            args=[sys.executable, "-m", http_server_module, str(port)],
            env=env,
            cwd=document_root,
            preexec_fn=os.setsid,
            bufsize=1,
            stdout=fp.fileno(),
            stderr=subprocess.STDOUT,
        )

    pidfile = Pidfile.record(server_log=log, pid=process.pid, timeout=timeout)
    if not pidfile:
        try:
            os.kill(process.pid, signal.SIGKILL)
        except OSError as e:
            if e.errno != errno.ESRCH:  # No such process.
                raise
        return log

    return LaunchResult(url=pidfile.url, already_running=False)


def shutdown_docs_server():
    # type: () -> bool

    pidfile = Pidfile.load()
    if not pidfile:
        return False

    logger.info(
        "Killing {server} {url} @ {pid}".format(
            server=SERVER_NAME, url=pidfile.url, pid=pidfile.pid
        )
    )
    pidfile.kill()
    return True


class Docs(BuildTimeCommand):
    """Interact with the Pex documentation."""

    def run(self):
        # type: () -> Result
        html_docs = docs.root(doc_type="html")
        if not html_docs:
            # TODO(John Sirois): Evaluate if this should fall back to opening latest html docs instead of just
            #  displaying links.
            return Error(
                dedent(
                    """\
                    This Pex distribution does not include embedded docs.

                    You can find the latest docs here:
                    HTML: https://docs.pex-tool.org
                     PDF: https://github.com/pex-tool/pex/releases/latest/download/pex.pdf
                    """
                ).rstrip()
            )

        # TODO(John Sirois): Consider trying a standard pex docs port, then fall back to ephemeral if:
        #  2.7: socket.error: [Errno 98] Address already in use
        #  3.x: OSError: [Errno 98] Address already in use
        #  This would allow for cookie stickiness for light / dark mode although the furo theme default of detecting
        #  the system default mode works well in practice to get you what you probably wanted anyhow.
        result = launch_docs_server(html_docs, port=0)
        if isinstance(result, str):
            with open(result) as fp:
                for line in fp:
                    logger.log(logging.ERROR, line.rstrip())
            return Error("Failed to launch {server}.".format(server=SERVER_NAME))

        logger.info(
            (
                "{server} already running at {url}"
                if result.already_running
                else "Launched {server} at {url}"
            ).format(server=SERVER_NAME, url=result.url)
        )
        return try_open_file(result.url)
