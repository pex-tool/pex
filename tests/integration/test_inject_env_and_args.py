# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import json
import os.path
import re
import signal
import socket
import subprocess
from contextlib import closing
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.fetcher import URLFetcher
from pex.typing import TYPE_CHECKING
from testing import IS_PYPY, PY_VER, make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any, Iterable, List, Optional


def test_inject_env_invalid():
    # type: () -> None
    result = run_pex_command(args=["--inject-env", "FOO"])
    result.assert_failure()
    assert "--inject-env" in result.error
    assert (
        "Environment variable values must be of the form `name=value`. Given: FOO" in result.error
    )


parametrize_execution_mode_args = pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--venv"], id="VENV"),
    ],
)


@parametrize_execution_mode_args
def test_inject_env(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    print_FOO_env_code = "import os; print(os.environ.get('FOO', '<not set>'))"

    pex = os.path.join(str(tmpdir), "pex")
    with open(os.path.join(str(tmpdir), "exe.py"), "w") as fp:
        fp.write(print_FOO_env_code)
    run_pex_command(
        args=["--inject-env", "FOO=bar", "--exe", fp.name, "-o", pex] + execution_mode_args
    ).assert_success()

    def assert_FOO(
        expected_env_value,  # type: str
        runtime_env_value=None,  # type: Optional[str]
    ):
        assert (
            expected_env_value
            == subprocess.check_output(args=[pex], env=make_env(FOO=runtime_env_value))
            .decode("utf-8")
            .strip()
        )

    assert_FOO(expected_env_value="bar")
    assert_FOO(expected_env_value="baz", runtime_env_value="baz")
    assert_FOO(expected_env_value="", runtime_env_value="")

    # Switching away from the built-in entrypoint should retain the injected env.
    assert (
        "bar"
        == subprocess.check_output(
            args=[pex, "-c", print_FOO_env_code], env=make_env(PEX_INTERPRETER=1, FOO="bar")
        )
        .decode("utf-8")
        .strip()
    )


DUMP_ARGS_CODE = "import json, sys; print(json.dumps(sys.argv[1:]))"


def create_inject_args_pex(
    tmpdir,  # type: Any
    execution_mode_args,  # type: Iterable[str]
    *inject_args  # type: str
):
    # type: (...) -> str
    pex = os.path.join(
        str(tmpdir),
        "pex-{}".format(hashlib.sha256(json.dumps(inject_args).encode("utf-8")).hexdigest()),
    )
    with open(os.path.join(str(tmpdir), "exe.py"), "w") as fp:
        fp.write(DUMP_ARGS_CODE)
    argv = ["--exe", fp.name, "-o", pex]
    for inject in inject_args:
        argv.append("--inject-args")
        argv.append(inject)
    argv.extend(execution_mode_args)
    run_pex_command(args=argv).assert_success()
    return pex


@parametrize_execution_mode_args
def test_inject_args(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex_individual = create_inject_args_pex(tmpdir, execution_mode_args, "foo", "bar")
    pex_shlex = create_inject_args_pex(tmpdir, execution_mode_args, "foo bar")
    pex_combined = create_inject_args_pex(tmpdir, execution_mode_args, "foo bar", "baz")

    def assert_argv(
        pex,  # type: str
        expected_argv,  # type: List[str]
        runtime_args=(),  # type: Iterable[str]
        **env
    ):
        assert expected_argv == json.loads(
            subprocess.check_output(args=[pex] + list(runtime_args), env=make_env(**env))
        )

    assert_argv(pex_individual, expected_argv=["foo", "bar"])
    assert_argv(pex_individual, expected_argv=["foo", "bar", "baz"], runtime_args=["baz"])
    assert_argv(pex_shlex, expected_argv=["foo", "bar"])
    assert_argv(pex_shlex, expected_argv=["foo", "bar", "baz"], runtime_args=["baz"])
    assert_argv(pex_combined, expected_argv=["foo", "bar", "baz"])
    assert_argv(pex_combined, expected_argv=["foo", "bar", "baz", "baz"], runtime_args=["baz"])

    # Switching away from the built-in entrypoint should disable injected args.
    assert_argv(
        pex_individual, expected_argv=[], runtime_args=["-c", DUMP_ARGS_CODE], PEX_INTERPRETER=1
    )
    assert_argv(pex_shlex, expected_argv=[], runtime_args=["-c", DUMP_ARGS_CODE], PEX_INTERPRETER=1)
    assert_argv(
        pex_combined, expected_argv=[], runtime_args=["-c", DUMP_ARGS_CODE], PEX_INTERPRETER=1
    )


@pytest.mark.skipif(
    PY_VER < (3, 7) or PY_VER >= (3, 12),
    reason=(
        "Uvicorn only supports Python 3.7+ and pre-built wheels are only available through 3.11."
    ),
)
@parametrize_execution_mode_args
def test_complex(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "example.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import json
                import os
                import sys


                async def app(scope, receive, send):
                    assert scope['type'] == 'http'

                    await send({
                        'type': 'http.response.start',
                        'status': 200,
                        'headers': [
                            [b'content-type', b'text/plain'],
                        ],
                    })
                    await send({
                        'type': 'http.response.body',
                        'body': os.environb.get(b'MESSAGE') or b'<message unset>',
                    })

                if __name__ == "__main__":
                    json.dump(
                        {"args": sys.argv[1:], "MESSAGE": os.environ.get("MESSAGE")}, sys.stdout
                    )
                """
            )
        )
    run_pex_command(
        args=[
            "-D",
            src,
            "uvicorn[standard]==0.18.3",
            "-c",
            "uvicorn",
            "--inject-args",
            "example:app",
            "--inject-env",
            "MESSAGE=Hello, world!",
            "-o",
            pex,
        ]
        + execution_mode_args
    ).assert_success()

    def assert_message(
        expected,  # type: bytes
        **env  # type: str
    ):
        # type: (...) -> None
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.bind(("127.0.0.1", 0))
            stderr_read_fd, stderr_write_fd = os.pipe()
            # Python 2.7 doesn't support pass_fds, but we don't test against Python2.7.
            process = subprocess.Popen(  # type: ignore[call-arg]
                args=[pex, "--fd", str(sock.fileno())],
                stderr=stderr_write_fd,
                pass_fds=[sock.fileno()],
                env=make_env(**env),
            )
            with os.fdopen(stderr_read_fd, "r") as stderr_fp:
                for line in stderr_fp:
                    if "Uvicorn running" in line:
                        break

            host, port = sock.getsockname()
            with URLFetcher().get_body_stream(
                "http://{host}:{port}".format(host=host, port=port)
            ) as fp:
                assert expected == fp.read()
            process.send_signal(signal.SIGINT)
            process.kill()
            os.close(stderr_write_fd)

    assert_message(b"Hello, world!")
    assert_message(b"42", MESSAGE="42")

    # Switching away from the built-in entrypoint should disable injected args but not the env.
    assert {"args": ["foo", "bar"], "MESSAGE": "Hello, world!"} == json.loads(
        subprocess.check_output(args=[pex, "foo", "bar"], env=make_env(PEX_MODULE="example"))
    )


@pytest.mark.skipif(
    IS_PYPY or PY_VER > (3, 10) or PY_VER < (3, 6),
    reason="The pyuwsgi distribution only has wheels for Linux and Mac for Python 3.6 through 3.10",
)
@parametrize_execution_mode_args
def test_pyuwsgi(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "myflaskapp.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from flask import Flask

                app = Flask(__name__)

                @app.route('/')
                def index():
                    return "I am app 1"
                """
            )
        )
    run_pex_command(
        args=[
            "-D",
            src,
            "pyuwsgi",
            "flask",
            "-c",
            "uwsgi",
            "--inject-args",
            "--master --module myflaskapp:app",
            "-o",
            pex,
        ]
        + execution_mode_args
    ).assert_success()

    stderr_read_fd, stderr_write_fd = os.pipe()
    process = subprocess.Popen(args=[pex, "--http-socket", "127.0.0.1:0"], stderr=stderr_write_fd)
    port = None  # type: Optional[str]
    with os.fdopen(stderr_read_fd, "r") as stderr_fp:
        for line in stderr_fp:
            match = re.search(r"bound to TCP address 127.0.0.1:(?P<port>\d+)", line)
            if match:
                port = match.group("port")
                break
    assert port is not None, "Could not determine uwsgi server port."
    with URLFetcher().get_body_stream("http://127.0.0.1:{port}".format(port=port)) as fp:
        assert b"I am app 1" == fp.read()
    process.send_signal(signal.SIGINT)
    process.kill()
    os.close(stderr_write_fd)
