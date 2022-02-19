# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
from contextlib import contextmanager
from textwrap import dedent

import pytest

from pex.common import atomic_directory, safe_mkdtemp, temporary_dir
from pex.testing import PY310, ensure_python_venv, make_env, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Callable, ContextManager, Iterator, Optional, Tuple


@pytest.fixture(scope="session")
def is_pytest_xdist(worker_id):
    # type: (str) -> bool
    return worker_id != "master"


@pytest.fixture(scope="session")
def shared_integration_test_tmpdir(
    tmpdir_factory,  # type: Any
    is_pytest_xdist,  # type: bool
):
    # type: (...) -> str
    tmpdir = str(tmpdir_factory.getbasetemp())

    # We know pytest-xdist creates a subdir under the pytest session tmp dir for each worker; so we
    # go up a level to lock a directory all workers can use.
    if is_pytest_xdist:
        tmpdir = os.path.dirname(tmpdir)

    return os.path.join(tmpdir, "shared_integration_test_tmpdir")


@pytest.fixture(scope="session")
def pex_bdist(
    pex_project_dir,  # type: str
    shared_integration_test_tmpdir,  # type: str
):
    # type: (...) -> str
    pex_bdist_chroot = os.path.join(shared_integration_test_tmpdir, "pex_bdist_chroot")
    wheels_dir = os.path.join(pex_bdist_chroot, "wheels_dir")
    with atomic_directory(pex_bdist_chroot, exclusive=True) as chroot:
        if not chroot.is_finalized():
            pex_pex = os.path.join(chroot.work_dir, "pex.pex")
            run_pex_command(
                args=[pex_project_dir, "-o", pex_pex, "--include-tools"]
            ).assert_success()
            extract_dir = os.path.join(chroot.work_dir, "wheels_dir")
            subprocess.check_call(
                args=[pex_pex, "repository", "extract", "-f", extract_dir],
                env=make_env(PEX_TOOLS=True),
            )
    wheels = os.listdir(wheels_dir)
    assert 1 == len(wheels)
    return os.path.join(wheels_dir, wheels[0])


@pytest.fixture
def tmp_workdir():
    # type: () -> Iterator[str]
    cwd = os.getcwd()
    with temporary_dir() as tmpdir:
        os.chdir(tmpdir)
        try:
            yield os.path.realpath(tmpdir)
        finally:
            os.chdir(cwd)


@pytest.fixture(scope="module")
def mitmdump():
    # type: () -> Tuple[str, str]
    python, pip = ensure_python_venv(PY310)
    with open(os.path.join(safe_mkdtemp(), "constraints.txt"), "w") as fp:
        fp.write(
            """\
            Brotli==1.0.9
            Jinja2==2.11.3
            MarkupSafe==2.0.1
            Werkzeug==1.0.1
            asgiref==3.3.4
            blinker==1.4
            certifi==2021.10.8
            cffi==1.15.0
            click==7.1.2
            cryptography==3.2.1
            flask==1.1.4
            h11==0.13.0
            h2==4.1.0
            hpack==4.0.0
            hyperframe==6.0.1
            itsdangerous==1.1.0
            kaitaistruct==0.9
            ldap3==2.8.1
            msgpack==1.0.3
            passlib==1.7.4
            protobuf==3.13.0
            publicsuffix2==2.20191221
            pyOpenSSL==19.1.0
            pyasn1==0.4.8
            pycparser==2.21
            pyparsing==2.4.7
            pyperclip==1.8.2
            ruamel.yaml==0.16.13
            six==1.16.0
            sortedcontainers==2.2.2
            tornado==6.1
            urwid==2.1.2
            wsproto==0.15.0
            zstandard==0.14.1
            """
        )
    subprocess.check_call([pip, "install", "mitmproxy==5.3.0", "--constraint", fp.name])
    mitmdump = os.path.join(os.path.dirname(python), "mitmdump")
    return mitmdump, os.path.expanduser("~/.mitmproxy/mitmproxy-ca-cert.pem")


@pytest.fixture
def run_proxy(mitmdump, tmp_workdir):
    # type: (Tuple[str, str], str) -> Callable[[Optional[str]], ContextManager[Tuple[int, str]]]
    messages = os.path.join(tmp_workdir, "messages")
    addon = os.path.join(tmp_workdir, "addon.py")
    with open(addon, "w") as fp:
        fp.write(
            dedent(
                """\
                from mitmproxy import ctx
        
                class NotifyUp:
                    def running(self) -> None:
                        port = ctx.master.server.address[1]
                        with open({msg_channel!r}, "w") as fp:
                            print(str(port), file=fp)
        
                addons = [NotifyUp()]
                """.format(
                    msg_channel=messages
                )
            )
        )

    @contextmanager
    def _run_proxy(
        proxy_auth=None,  # type: Optional[str]
    ):
        # type: (...) -> Iterator[Tuple[int, str]]
        os.mkfifo(messages)
        proxy, ca_cert = mitmdump
        args = [proxy, "-p", "0", "-s", addon]
        if proxy_auth:
            args.extend(["--proxyauth", proxy_auth])
        proxy_process = subprocess.Popen(args)
        try:
            with open(messages, "r") as fp:
                port = int(fp.readline().strip())
                yield port, ca_cert
        finally:
            proxy_process.kill()
            os.unlink(messages)

    return _run_proxy
