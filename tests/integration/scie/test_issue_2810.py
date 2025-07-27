# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
import sys

import pytest

from pex.atomic_directory import atomic_directory
from pex.http.server import Server, ServerInfo
from pex.scie.science import SCIE_JUMP_VERSION, ensure_science
from pex.typing import TYPE_CHECKING
from testing import IS_MAC, make_env, run_pex_command
from testing.mitmproxy import Proxy
from testing.pytest_utils import IS_CI
from testing.pytest_utils.tmp import Tempdir
from testing.scie import provider, skip_if_no_provider

if TYPE_CHECKING:
    from typing import Iterator


@pytest.fixture(scope="session")
def scie_assets_dir(shared_integration_test_tmpdir):
    # type: (str) -> str

    lock_dir = os.path.join(shared_integration_test_tmpdir, "scie_assets")
    with atomic_directory(lock_dir) as atomic_dir:
        if not atomic_dir.is_finalized():
            science = ensure_science()
            subprocess.check_call(
                args=[
                    science,
                    "download",
                    "scie-jump",
                    "--version",
                    SCIE_JUMP_VERSION,
                    atomic_dir.work_dir,
                ]
            )
            subprocess.check_call(
                args=[
                    science,
                    "download",
                    "provider",
                    str(provider()),
                    "--version",
                    ".".join(map(str, sys.version_info[:2])),
                    atomic_dir.work_dir,
                ]
            )
        return lock_dir


@pytest.fixture
def scie_assets_server(
    tmpdir,  # type: Tempdir
    scie_assets_dir,  # type: str
):
    # type: (...) -> Iterator[ServerInfo]
    server = Server(name="Test Providers Server", cache_dir=tmpdir.join("server"))
    result = server.launch(
        scie_assets_dir,
        timeout=float(os.environ.get("_PEX_HTTP_SERVER_TIMEOUT", "5.0")),
        verbose_error=True,
    )
    try:
        yield result.server_info
    finally:
        server.shutdown()


CI_skip_mac = pytest.mark.xfail(
    IS_CI and IS_MAC,
    reason=(
        "The scie asset server fails to start, at least on the macos-15 CI runners, and since this "
        "is not a multi-platform test, just checking on Linux is not ideal but good enough."
    ),
)


@CI_skip_mac
@skip_if_no_provider
def test_proxy_args(
    tmpdir,  # type: Tempdir
    scie_assets_server,  # type: ServerInfo
    proxy,  # type: Proxy
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex_root")
    cowsay_scie = tmpdir.join("cowsay")
    with proxy.run() as (port, cert):
        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--proxy",
                "http://localhost:{port}".format(port=port),
                "--cert",
                cert,
                "cowsay<6",
                "-c",
                "cowsay",
                "--scie",
                "eager",
                "--scie-only",
                "--scie-assets-base-url",
                scie_assets_server.url,
                "-o",
                cowsay_scie,
            ],
        ).assert_success()

    assert b"| Moo! |" in subprocess.check_output(args=[cowsay_scie, "Moo!"])


@CI_skip_mac
@skip_if_no_provider
def test_proxy_env(
    tmpdir,  # type: Tempdir
    scie_assets_server,  # type: ServerInfo
    proxy,  # type: Proxy
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex_root")
    cowsay_scie = tmpdir.join("cowsay")
    with proxy.run() as (port, cert):
        proxy_url = "http://localhost:{port}".format(port=port)
        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "cowsay<6",
                "-c",
                "cowsay",
                "--scie",
                "eager",
                "--scie-only",
                "--scie-assets-base-url",
                scie_assets_server.url,
                "-o",
                cowsay_scie,
            ],
            env=make_env(
                http_proxy=proxy_url,
                https_proxy=proxy_url,
                SSL_CERT_FILE=cert,
            ),
        ).assert_success()

    assert b"| Moo! |" in subprocess.check_output(args=[cowsay_scie, "Moo!"])
