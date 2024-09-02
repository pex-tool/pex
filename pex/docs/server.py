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

from pex.cache.dirs import CacheDir
from pex.common import safe_open
from pex.typing import TYPE_CHECKING
from pex.version import __version__

if TYPE_CHECKING:
    from typing import Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


logger = logging.getLogger(__name__)

SERVER_NAME = "Pex v{version} docs HTTP server".format(version=__version__)

_SERVER_DIR = CacheDir.DOCS.path("server", __version__)


@attr.s(frozen=True)
class ServerInfo(object):
    url = attr.ib()  # type: str
    pid = attr.ib()  # type: int

    def __str__(self):
        # type: () -> str
        return "{url} @ {pid}".format(url=self.url, pid=self.pid)


@attr.s(frozen=True)
class Pidfile(object):
    _PIDFILE = os.path.join(_SERVER_DIR, "pidfile")

    @classmethod
    def load(cls):
        # type: () -> Optional[Pidfile]
        try:
            with open(cls._PIDFILE) as fp:
                data = json.load(fp)
            return cls(ServerInfo(url=data["url"], pid=data["pid"]))
        except (OSError, IOError, ValueError, KeyError) as e:
            logger.debug(
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
                        match = re.search(r"Serving HTTP on 0\.0\.0\.0 port (?P<port>\d+)", line)
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
        return cls(ServerInfo(url=url, pid=pid))

    server_info = attr.ib()  # type: ServerInfo

    def alive(self):
        # type: () -> bool
        # TODO(John Sirois): Handle pid rollover
        try:
            os.kill(self.server_info.pid, 0)
            return True
        except OSError as e:
            if e.errno == errno.ESRCH:  # No such process.
                return False
            raise

    def kill(self):
        # type: () -> None
        os.kill(self.server_info.pid, signal.SIGTERM)


@attr.s(frozen=True)
class LaunchResult(object):
    server_info = attr.ib()  # type: ServerInfo
    already_running = attr.ib()  # type: bool


# Frozen exception types don't work under 3.11+ where the `__traceback__` attribute can be set
# after construction in some cases.
@attr.s
class LaunchError(Exception):
    """Indicates an error launching the docs server."""

    log = attr.ib()  # type: str
    additional_msg = attr.ib(default=None)  # type: Optional[str]

    def __str__(self):
        # type: () -> str
        lines = ["Error launching docs server."]
        if self.additional_msg:
            lines.append(self.additional_msg)
        lines.append("See the log at {log} for more details.".format(log=self.log))
        return os.linesep.join(lines)


def launch(
    document_root,  # type: str
    port,  # type: int
    timeout=5.0,  # type: float
):
    # type: (...) -> LaunchResult

    pidfile = Pidfile.load()
    if pidfile and pidfile.alive():
        return LaunchResult(server_info=pidfile.server_info, already_running=True)

    # Not proper daemonization, but good enough.
    log = os.path.join(_SERVER_DIR, "log.txt")
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
                raise LaunchError(
                    log,
                    additional_msg=(
                        "Also failed to kill the partially launched server at pid {pid}: "
                        "{err}".format(pid=process.pid, err=e)
                    ),
                )
        raise LaunchError(log)
    return LaunchResult(server_info=pidfile.server_info, already_running=False)


def shutdown():
    # type: () -> Optional[ServerInfo]

    pidfile = Pidfile.load()
    if not pidfile or not pidfile.alive():
        return None

    logger.debug("Killing {server} {info}".format(server=SERVER_NAME, info=pidfile.server_info))
    pidfile.kill()
    return pidfile.server_info
