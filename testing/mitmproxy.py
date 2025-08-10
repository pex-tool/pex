from __future__ import absolute_import

import json
import logging
import os
import subprocess
from contextlib import contextmanager
from textwrap import dedent

from pex.atomic_directory import atomic_directory
from pex.common import safe_rmtree
from pex.interpreter import PythonInterpreter
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper
from pex.venv.virtualenv import InvalidVirtualenvError, Virtualenv
from testing import PEX_TEST_DEV_ROOT, PY311, data, ensure_python_interpreter

if TYPE_CHECKING:
    from typing import Iterable, Iterator, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


logger = logging.getLogger(__name__)


MITMPROXY_DIR = os.path.join(PEX_TEST_DEV_ROOT, "mitmproxy")


def _ensure_mitmproxy_venv():
    # type: () -> Virtualenv

    mitmproxy_lock = data.path("locks", "mitmproxy.lock.json")
    venv_dir = os.path.join(MITMPROXY_DIR, CacheHelper.hash(mitmproxy_lock), "venv")
    try:
        return Virtualenv(venv_dir=venv_dir)
    except InvalidVirtualenvError as e:
        logger.warning(str(e))
        safe_rmtree(venv_dir)
        with atomic_directory(venv_dir) as atomic_venvdir:
            if not atomic_venvdir.is_finalized():
                logger.info("Installing mitmproxy...")
                python = ensure_python_interpreter(PY311)
                Virtualenv.create_atomic(
                    venv_dir=atomic_venvdir,
                    interpreter=PythonInterpreter.from_binary(python),
                    force=True,
                )
                subprocess.check_call(
                    args=[
                        python,
                        "-m",
                        "pex.cli",
                        "venv",
                        "create",
                        "--pip-version",
                        "latest-compatible",
                        "--lock",
                        mitmproxy_lock,
                        "-d",
                        atomic_venvdir.work_dir,
                    ]
                )
        return Virtualenv(venv_dir=venv_dir)


@attr.s(frozen=True)
class Proxy(object):
    @classmethod
    def configured(cls, config_dir):
        # type: (str) -> Proxy

        mitmdump_venv = _ensure_mitmproxy_venv()

        confdir = os.path.join(config_dir, "confdir")
        messages = os.path.join(config_dir, "messages")
        addon = os.path.join(config_dir, "addon.py")
        with open(addon, "w") as fp:
            fp.write(
                dedent(
                    """\
                    import json

                    from mitmproxy import ctx


                    def running() -> None:
                        port = ctx.master.addons.get("proxyserver").listen_addrs()[0][1]
                        with open({msg_channel!r}, "w") as fp:
                            json.dump({{"port": port}}, fp)
                    """.format(
                        msg_channel=messages
                    )
                )
            )
        return cls(mitmdump_venv=mitmdump_venv, confdir=confdir, messages=messages, addon=addon)

    mitmdump_venv = attr.ib()  # type Virtualenv
    confdir = attr.ib()  # type: str
    messages = attr.ib()  # type: str
    addon = attr.ib()  # type: str

    @contextmanager
    def reverse(
        self,
        targets,  # type: Iterable[str]
        proxy_auth=None,  # type: Optional[str]
        dump_headers=False,  # type: bool
    ):
        # type: (...) -> Iterator[Tuple[int, str]]
        os.mkfifo(self.messages)
        args = [
            self.mitmdump_venv.interpreter.binary,
            self.mitmdump_venv.bin_path("mitmdump"),
            "--set",
            "confdir={confdir}".format(confdir=self.confdir),
            "--set",
            "flow_detail={level}".format(level="2" if dump_headers else "1"),
            "-p",
            "0",
            "-s",
            self.addon,
        ]
        if proxy_auth:
            args.extend(["--proxyauth", proxy_auth])
        for target in targets:
            args.extend(["--mode", "reverse:{target}".format(target=target)])
        proxy_process = subprocess.Popen(args)
        try:
            with open(self.messages, "r") as fp:
                data = json.load(fp)
            yield data["port"], os.path.join(self.confdir, "mitmproxy-ca.pem")
        finally:
            proxy_process.kill()
            os.unlink(self.messages)

    @contextmanager
    def run(
        self,
        proxy_auth=None,  # type: Optional[str]
        dump_headers=False,  # type: bool
    ):
        # type: (...) -> Iterator[Tuple[int, str]]

        with self.reverse(targets=(), proxy_auth=proxy_auth, dump_headers=dump_headers) as (
            port,
            cert,
        ):
            yield port, cert
