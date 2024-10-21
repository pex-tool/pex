# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import base64
import os.path
from contextlib import contextmanager
from threading import Thread

import colors  # vendor:skip
import pytest

from pex.common import safe_rmtree
from pex.compatibility import PY2
from pex.typing import TYPE_CHECKING
from testing import IntegResults, make_env, run_pex_command
from testing.cli import run_pex3
from testing.pytest.tmp import TempdirFactory

if TYPE_CHECKING:
    from typing import Any, Iterator

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Address(object):
    host = attr.ib()  # type: str
    port = attr.ib()  # type: int


@contextmanager
def serve_authenticated(username, password, find_links):
    expected_authorization = "Basic {}".format(
        base64.b64encode(
            "{username}:{password}".format(username=username, password=password).encode("utf8")
        ).decode("utf-8")
    )

    if PY2:
        from BaseHTTPServer import HTTPServer as HTTPServer
        from SimpleHTTPServer import SimpleHTTPRequestHandler as SimpleHTTPRequestHandler
    else:
        from http.server import HTTPServer as HTTPServer
        from http.server import SimpleHTTPRequestHandler as SimpleHTTPRequestHandler

    class BasicHTTPAuthHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            authorization = self.headers.get("Authorization")
            if expected_authorization == authorization:
                SimpleHTTPRequestHandler.do_GET(self)
            else:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="Foo"')
                self.end_headers()

    server = HTTPServer(("", 0), BasicHTTPAuthHandler)
    server_dispatch_thread = Thread(target=server.serve_forever)
    server_dispatch_thread.daemon = True
    cwd = os.getcwd()
    try:
        os.chdir(find_links)
        server_dispatch_thread.start()
        host, port = server.server_address
        yield Address(host=host, port=port)
    finally:
        server.shutdown()
        server_dispatch_thread.join()
        os.chdir(cwd)


@pytest.fixture(scope="module")
def ansicolors_find_links_directory(
    tmpdir_factory,  # type: TempdirFactory
    request,  # type: Any
):
    # type: (...) -> str
    find_links = str(tmpdir_factory.mktemp("find_links", request=request))
    run_pex_command(
        args=[
            "ansicolors==1.1.8",
            "--include-tools",
            "--",
            "repository",
            "extract",
            "--find-links",
            find_links,
        ],
        env=make_env(PEX_TOOLS=1),
    ).assert_success()
    return find_links


@attr.s(frozen=True)
class SecuredLock(object):
    repo_address = attr.ib()  # type: Address
    repo_username = attr.ib()  # type: str
    repo_password = attr.ib()  # type: str
    lock = attr.ib()  # type: str
    pex_root = attr.ib()  # type: str

    @property
    def repo_url(self):
        # type: () -> str
        return "http://{host}:{port}".format(
            host=self.repo_address.host, port=self.repo_address.port
        )

    @property
    def repo_url_with_credentials(self):
        # type: () -> str
        return "http://{username}:{password}@{host}:{port}".format(
            username=self.repo_username,
            password=self.repo_password,
            host=self.repo_address.host,
            port=self.repo_address.port,
        )


@pytest.fixture
def secured_ansicolors_lock(
    ansicolors_find_links_directory,  # type: str
    tmpdir,  # type: Any
):
    # type: (...) -> Iterator[SecuredLock]

    username = "joe"
    password = "bob"
    with serve_authenticated(
        username=username,
        password=password,
        find_links=ansicolors_find_links_directory,
    ) as address:
        lock = os.path.join(str(tmpdir), "lock")
        pex_root = os.path.join(str(tmpdir), "pex_root")
        secured_lock = SecuredLock(
            repo_address=address,
            repo_username=username,
            repo_password=password,
            lock=lock,
            pex_root=pex_root,
        )

        run_pex3(
            "lock",
            "create",
            "--pex-root",
            pex_root,
            "--no-pypi",
            "--find-links",
            secured_lock.repo_url_with_credentials,
            # Since we have no PyPI access, ensure we're using vendored Pip for this test.
            "--pip-version=vendored",
            "ansicolors",
            "--indent",
            "2",
            "-o",
            lock,
        ).assert_success()
        yield secured_lock


def assert_unauthorized(
    secured_ansicolors_lock,  # type: SecuredLock
    result,  # type: IntegResults
):
    # type: (...) -> IntegResults
    result.assert_failure()
    assert (
        "There was 1 error downloading required artifacts:\n"
        "1. ansicolors 1.1.8 from {repo_url}/ansicolors-1.1.8-py2.py3-none-any.whl\n"
        "    pip: ERROR: Could not install requirement ansicolors==1.1.8 from "
        "{repo_url}/ansicolors-1.1.8-py2.py3-none-any.whl because of HTTP error 401 Client Error: "
        "Unauthorized for url: {repo_url}/ansicolors-1.1.8-py2.py3-none-any.whl for URL "
        "{repo_url}/ansicolors-1.1.8-py2.py3-none-any.whl".format(
            repo_url=secured_ansicolors_lock.repo_url
        )
    ) in result.error, result.error

    return result


def test_authenticated_lock_url_issue_1753(
    tmpdir,  # type: Any
    secured_ansicolors_lock,  # type: SecuredLock
):
    # type: (...) -> None

    use_lock_command_unauthenticated = [
        "--pex-root",
        secured_ansicolors_lock.pex_root,
        "--lock",
        secured_ansicolors_lock.lock,
        "--",
        "-c",
        "import colors; print(colors.red('Authenticated'))",
    ]

    def assert_success(result):
        # type: (IntegResults) -> None
        result.assert_success()
        assert colors.red("Authenticated") == result.output.strip()

    # N.B.: Since we created the lock locally, the Pex cache will contain the artifacts needed
    # and no fetches will need to be performed; so, even though we're running without
    # credentials, we should succeed anyhow.
    assert_success(run_pex_command(args=use_lock_command_unauthenticated))

    # But with the Pex caches cleared, fetches should be forced and they should fail without
    # credentials.
    safe_rmtree(secured_ansicolors_lock.pex_root)
    assert_unauthorized(
        secured_ansicolors_lock, run_pex_command(args=use_lock_command_unauthenticated)
    )

    # The find links repo URL without embedded credentials shouldn't help.
    assert_unauthorized(
        secured_ansicolors_lock,
        run_pex_command(
            args=[
                "--find-links",
                secured_ansicolors_lock.repo_url,
            ]
            + use_lock_command_unauthenticated
        ),
    )

    assert_success(
        run_pex_command(
            args=[
                "--find-links",
                secured_ansicolors_lock.repo_url_with_credentials,
            ]
            + use_lock_command_unauthenticated
        )
    )


def test_authenticated_lock_netrc_issue_1753(
    tmpdir,  # type: Any
    secured_ansicolors_lock,  # type: SecuredLock
):
    # type: (...) -> None

    # We don't expect the ambient ~/.netrc, if present, will have the right credentials for an
    # ephemeral port server.
    use_lock_command = [
        "--pex-root",
        secured_ansicolors_lock.pex_root,
        "--lock",
        secured_ansicolors_lock.lock,
        "--",
        "-c",
        "import colors; print(colors.blue('Login Successful'))",
    ]
    safe_rmtree(secured_ansicolors_lock.pex_root)
    assert_unauthorized(secured_ansicolors_lock, run_pex_command(args=use_lock_command))

    # This explicitly controlled ~/.netrc definitely doesn't have the right credentials.
    home = os.path.join(str(tmpdir), "home")
    os.mkdir(home)
    with open(os.path.join(home, ".netrc"), "w") as fp:
        print("machine foo login bar password baz", file=fp)
    assert_unauthorized(
        secured_ansicolors_lock, run_pex_command(args=use_lock_command, env=make_env(HOME=home))
    )

    def assert_authorized(result):
        # type: (IntegResults) -> None
        result.assert_success()
        assert colors.blue("Login Successful") == result.output.strip()

    with open(os.path.join(home, ".netrc"), "a") as fp:
        print(
            "machine {host}:{port} login {username} password {password}".format(
                host=secured_ansicolors_lock.repo_address.host,
                port=secured_ansicolors_lock.repo_address.port,
                username=secured_ansicolors_lock.repo_username,
                password=secured_ansicolors_lock.repo_password,
            ),
            file=fp,
        )
    assert_authorized(run_pex_command(args=use_lock_command, env=make_env(HOME=home)))

    with open(os.path.join(home, ".netrc"), "w") as fp:
        print(
            "machine {url} login {username} password {password}".format(
                url=secured_ansicolors_lock.repo_url,
                username=secured_ansicolors_lock.repo_username,
                password=secured_ansicolors_lock.repo_password,
            ),
            file=fp,
        )
    safe_rmtree(secured_ansicolors_lock.pex_root)
    assert_authorized(run_pex_command(args=use_lock_command, env=make_env(HOME=home)))

    with open(os.path.join(home, ".netrc"), "w") as fp:
        print(
            "default login {username} password {password}".format(
                username=secured_ansicolors_lock.repo_username,
                password=secured_ansicolors_lock.repo_password,
            ),
            file=fp,
        )
    safe_rmtree(secured_ansicolors_lock.pex_root)
    assert_authorized(run_pex_command(args=use_lock_command, env=make_env(HOME=home)))


def test_bad_netrc_issue_1762(
    tmpdir,  # type: Any
    secured_ansicolors_lock,  # type: SecuredLock
):
    # type: (...) -> None

    use_lock_command = [
        "--pex-root",
        secured_ansicolors_lock.pex_root,
        "--lock",
        secured_ansicolors_lock.lock,
        "--",
        "-c",
        "import colors; print(colors.yellow('Welcome'))",
    ]
    safe_rmtree(secured_ansicolors_lock.pex_root)

    home = os.path.join(str(tmpdir), "home")
    os.mkdir(home)
    netrc_path = os.path.join(home, ".netrc")
    with open(netrc_path, "w") as fp:
        print("default login foo password bar", file=fp)
        print("machine foo login bar password baz", file=fp)
        print(
            "machine {host}:{port} login {username} password {password} protocol http".format(
                host=secured_ansicolors_lock.repo_address.host,
                port=secured_ansicolors_lock.repo_address.port,
                username=secured_ansicolors_lock.repo_username,
                password=secured_ansicolors_lock.repo_password,
            ),
            file=fp,
        )

    def assert_netrc_skipped(result):
        # type: (IntegResults) -> None
        assert (
            "Failed to load netrc credentials: bad follower token 'protocol' ({netrc}, line 3)\n"
            "Continuing without netrc credentials.".format(netrc=netrc_path)
        ) in result.error

    result = assert_unauthorized(
        secured_ansicolors_lock,
        run_pex_command(args=use_lock_command, env=make_env(HOME=home), quiet=True),
    )
    assert_netrc_skipped(result)

    result = run_pex_command(
        args=["--find-links", secured_ansicolors_lock.repo_url_with_credentials] + use_lock_command,
        env=make_env(HOME=home),
        quiet=True,
    )
    result.assert_success()
    assert_netrc_skipped(result)
    assert colors.yellow("Welcome") == result.output.strip()
