# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import os.path
import subprocess
from contextlib import contextmanager
from textwrap import dedent

import colors
import pytest

from pex.cli.testing import run_pex3
from pex.common import safe_mkdtemp, safe_rmtree
from pex.testing import PY37, IntegResults, ensure_python_interpreter, make_env, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Iterator

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Address(object):
    host = attr.ib()  # type: str
    port = attr.ib()  # type: int


@attr.s(frozen=True)
class TinyHttpServer(object):
    PID_FILE_ENV_VAR_NAME = "__PID_FILE__"

    binary = attr.ib()  # type: str

    @contextmanager
    def serve_authenticated(
        self,
        username,  # type: str
        password,  # type: str
        find_links,  # type: str
    ):
        # type: (...) -> Iterator[Address]
        pid_file = os.path.join(safe_mkdtemp(), "pid")
        os.mkfifo(pid_file)
        env = os.environ.copy()
        env[self.PID_FILE_ENV_VAR_NAME] = pid_file
        process = subprocess.Popen(
            args=[
                self.binary,
                "--auth",
                "{username}:{password}".format(username=username, password=password),
                "--port",
                "0",
                "--directory",
                find_links,
            ],
            env=env,
        )
        try:
            with open(pid_file) as fp:
                host, port = fp.readline().strip().split(":")
            yield Address(host, int(port))
        finally:
            process.kill()


@pytest.fixture(scope="module")
def tiny_http_server(tmpdir_factory):
    # type: (Any) -> TinyHttpServer
    pex_file = str(tmpdir_factory.mktemp("pexes").join("tiny-http-server.pex"))
    src = tmpdir_factory.mktemp("srcs")
    with open(str(src.join("exe.py")), "w") as fp:
        # N.B.: The tiny-http-server has a handy basic-auth implementation, but it will not emit its
        # random port to stdout unless stdout is a TTY. Here we use pexpect to arrange for that.
        fp.write(
            dedent(
                """\
                import atexit
                import os
                import sys

                import pexpect


                child = pexpect.spawn("tiny-http-server", sys.argv[1:], encoding="utf-8")
                atexit.register(child.terminate, force=True)
                
                child.expect(r"^Serving HTTP on (?P<host>\\S+) port (?P<port>\\d+) ")
                with open(os.environ[{pid_file_env_var_name!r}], "w") as fp:
                    print(f"{{child.match.group('host')}}:{{child.match.group('port')}}", file=fp)
                
                # Serve forever.
                child.wait()
                """.format(
                    pid_file_env_var_name=TinyHttpServer.PID_FILE_ENV_VAR_NAME
                )
            )
        )

    # N.B.: tiny-http-server requires Python >= 3.7.
    python = ensure_python_interpreter(PY37)
    run_pex_command(
        args=[
            "tiny-http-server==0.1",
            "pexpect==4.8.0",
            "-D",
            str(src),
            "-m",
            "exe",
            "-o",
            pex_file,
            "--venv",
            "prepend",
        ],
        python=python,
    ).assert_success()
    return TinyHttpServer(binary=pex_file)


@pytest.fixture(scope="module")
def ansicolors_find_links_directory(tmpdir_factory):
    # type: (Any) -> str
    find_links = str(tmpdir_factory.mktemp("find_links"))
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
    tiny_http_server,  # TinyHttpServer
    ansicolors_find_links_directory,  # type: str
    tmpdir,  # type: Any
):
    # type: (...) -> Iterator[SecuredLock]

    username = "joe"
    password = "bob"
    with tiny_http_server.serve_authenticated(
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
    # type: (...) -> None
    result.assert_failure()
    assert (
        "There was 1 error downloading required artifacts:\n"
        "1. ansicolors 1.1.8 from {repo_url}/ansicolors-1.1.8-py2.py3-none-any.whl\n"
        "    HTTP Error 401: Unauthorized".format(repo_url=secured_ansicolors_lock.repo_url)
    ) in result.error


def test_authenticated_lock_url(
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


def test_authenticated_lock_netrc(
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
