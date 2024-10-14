# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import errno
import json
import logging
import os
import re
import signal
import subprocess
import time

import psutil  # type: ignore[import]

from pex.atomic_directory import atomic_directory
from pex.common import safe_open, safe_rmtree
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import InterpreterConstraint
from pex.typing import TYPE_CHECKING, cast
from pex.venv.virtualenv import InvalidVirtualenvError, Virtualenv
from testing import PEX_TEST_DEV_ROOT

if TYPE_CHECKING:
    from typing import List, Optional, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


logger = logging.getLogger(__name__)


DEVPI_DIR = os.path.join(PEX_TEST_DEV_ROOT, "devpi")


@attr.s(frozen=True)
class Pidfile(object):
    _PATH = os.path.join(DEVPI_DIR, "pidfile")

    @classmethod
    def load(cls):
        # type: () -> Optional[Pidfile]
        try:
            with open(cls._PATH) as fp:
                data = json.load(fp)
            return cls(url=data["url"], pid=data["pid"], create_time=data["create_time"])
        except (OSError, IOError, ValueError, KeyError) as e:
            logger.warning(
                "Failed to load devpi-server pid file from {path}: {err}".format(
                    path=cls._PATH, err=e
                )
            )
            return None

    @staticmethod
    def _read_base_url(
        log,  # type: str
        timeout,  # type: float
    ):
        # type: (...) -> Optional[str]
        start = time.time()
        while time.time() - start < timeout:
            with open(log) as fp:
                for line in fp:
                    if line.endswith(os.linesep):
                        match = re.search(r"Serving on (?P<url>http://\S+)$", line)
                        if match:
                            return match.group("url")
        return None

    @staticmethod
    def _get_process_creation_time(pid):
        # type: (int) -> Optional[float]
        try:
            return cast(float, psutil.Process(pid).create_time())
        except psutil.Error:
            return None

    @classmethod
    def record(
        cls,
        log,  # type: str
        pid,  # type: int
        timeout=5.0,  # type: float
    ):
        # type: (...) -> Optional[Pidfile]
        base_url = cls._read_base_url(log, timeout)
        if not base_url:
            return None

        create_time = cls._get_process_creation_time(pid)
        if create_time is None:
            return None

        url = "{base_url}/root/pypi/+simple/".format(base_url=base_url)
        with safe_open(cls._PATH, "w") as fp:
            json.dump(dict(url=url, pid=pid, create_time=create_time), fp, indent=2, sort_keys=True)
        return cls(url=url, pid=pid, create_time=create_time)

    url = attr.ib()  # type: str
    pid = attr.ib()  # type: int
    create_time = attr.ib()  # type: float

    def alive(self):
        # type: () -> bool
        return self.create_time == self._get_process_creation_time(self.pid)

    def kill(self):
        # type: () -> None
        os.kill(self.pid, signal.SIGTERM)


@attr.s(frozen=True)
class DevpiServer(object):
    python = attr.ib()  # type: str
    script = attr.ib()  # type: str
    serverdir = attr.ib()  # type: str

    def launch_args(self, *extra_args):
        # type: (*str) -> List[str]
        return [self.python, self.script, "--serverdir", self.serverdir] + list(extra_args)


def ensure_devpi_server():
    # type: () -> DevpiServer

    venv_dir = os.path.join(DEVPI_DIR, "venv")
    try:
        venv = Virtualenv(venv_dir=venv_dir)
    except InvalidVirtualenvError as e:
        logger.warning(str(e))
        safe_rmtree(venv_dir)
        with atomic_directory(venv_dir) as atomic_venvdir:
            if not atomic_venvdir.is_finalized():
                logger.info("Installing devpi-server...")
                lock = os.path.join(os.path.dirname(__file__), "devpi-server.lock")
                python = PythonInterpreter.latest_release_of_min_compatible_version(
                    InterpreterConstraint.parse(">=3.8,<3.13").iter_matching()
                )
                Virtualenv.create_atomic(venv_dir=atomic_venvdir, interpreter=python, force=True)
                subprocess.check_call(
                    args=[
                        python.binary,
                        "-m",
                        "pex.cli",
                        "venv",
                        "create",
                        "--lock",
                        lock,
                        "-d",
                        atomic_venvdir.work_dir,
                    ]
                )
        venv = Virtualenv(venv_dir=venv_dir)

    serverdir = os.path.join(DEVPI_DIR, "serverdir")
    with atomic_directory(serverdir) as atomic_serverdir:
        if not atomic_serverdir.is_finalized():
            logger.info("Initializing devpi-server...")
            logger.info("Using {}".format(venv.bin_path("devpi-init")))
            subprocess.check_call(
                args=[
                    venv.interpreter.binary,
                    venv.bin_path("devpi-init"),
                    "--serverdir",
                    atomic_serverdir.work_dir,
                ]
            )

    return DevpiServer(
        python=venv.interpreter.binary, script=venv.bin_path("devpi-server"), serverdir=serverdir
    )


@attr.s(frozen=True)
class LaunchResult(object):
    url = attr.ib()  # type: str
    already_running = attr.ib()  # type: bool


def launch(
    host,  # type: str
    port,  # type: int
    timeout,  # type: float
    max_connection_retries,  # type: int
    request_timeout,  # type: int
):
    # type: (...) -> Union[str, LaunchResult]

    pidfile = Pidfile.load()
    if pidfile and pidfile.alive():
        return LaunchResult(url=pidfile.url, already_running=True)

    devpi_server = ensure_devpi_server()

    # Not proper daemonization, but good enough.
    log = os.path.join(DEVPI_DIR, "log.txt")
    with safe_open(log, "w") as fp:
        process = subprocess.Popen(
            args=devpi_server.launch_args(
                "--host",
                host,
                "--port",
                str(port),
                "--replica-max-retries",
                str(max_connection_retries),
                "--request-timeout",
                str(request_timeout),
            ),
            cwd=DEVPI_DIR,
            preexec_fn=os.setsid,
            stdout=fp.fileno(),
            stderr=subprocess.STDOUT,
        )

    pidfile = Pidfile.record(log=log, pid=process.pid, timeout=timeout)
    if not pidfile:
        try:
            os.kill(process.pid, signal.SIGKILL)
        except OSError as e:
            if e.errno != errno.ESRCH:  # No such process.
                raise
        return log

    return LaunchResult(url=pidfile.url, already_running=False)


def shutdown():
    # type: () -> bool

    pidfile = Pidfile.load()
    if not pidfile:
        return False

    logger.info("Killing devpi server {url} @ {pid}".format(url=pidfile.url, pid=pidfile.pid))
    pidfile.kill()
    return True
