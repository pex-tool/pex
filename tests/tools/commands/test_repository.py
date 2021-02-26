# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import signal
import subprocess
from textwrap import dedent

import pytest

from pex.common import safe_open, temporary_dir
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict, Iterator


FABRIC_VERSION = "2.5.0"


@pytest.fixture(scope="module")
def pex():
    # type: () -> Iterator[str]
    with temporary_dir() as tmpdir:
        pex_path = os.path.join(tmpdir, "example.pex")

        src = os.path.join(tmpdir, "src")
        with safe_open(os.path.join(src, "data", "url.txt"), "w") as fp:
            fp.write("https://example.com")
        with safe_open(os.path.join(src, "main.py"), "w") as fp:
            fp.write(
                dedent(
                    """\
                    from __future__ import print_function

                    import os
                    import sys

                    import requests


                    def do():
                        with open(os.path.join(os.path.dirname(__file__), "data", "url.txt")) as fp:
                            url = fp.read().strip()
                        print("Fetching from {} ...".format(url))
                        print(requests.get(url).text, file=sys.stderr)
                    """
                )
            )
        result = run_pex_command(
            args=[
                "-D",
                src,
                "requests==2.25.1",
                "-e",
                "main:do",
                "--interpreter-constraint",
                "CPython>=2.7,<4",
                "-o",
                pex_path,
                "--include-tools",
            ],
        )
        result.assert_success()
        yield os.path.realpath(pex_path)


def make_env(**kwargs):
    # type: (**Any) -> Dict[str, str]
    env = os.environ.copy()
    env.update((k, str(v)) for k, v in kwargs.items())
    return env


def test_wheel_included(pex, tmpdir):
    # type: (str, Any) -> None
    dists_dir = os.path.join(str(tmpdir), "dists")
    pid_file = os.path.join(str(tmpdir), "pid")
    os.mkfifo(pid_file)
    find_links_server = subprocess.Popen(
        args=[
            pex,
            "repository",
            "extract",
            "--serve",
            "--sources",
            "--dest-dir",
            dists_dir,
            "--pid-file",
            pid_file,
        ],
        env=make_env(PEX_TOOLS=1),
        stdout=subprocess.PIPE,
    )
    with open(pid_file) as fp:
        _, port = fp.read().strip().split(":", 1)
    example_sdist_pex = os.path.join(str(tmpdir), "example-sdist.pex")
    result = run_pex_command(
        args=[
            "--no-pypi",
            "--find-links",
            "http://localhost:{}".format(port),
            "example",
            "-c",
            "example",
            "-o",
            example_sdist_pex,
        ]
    )
    result.assert_success()

    find_links_server.send_signal(signal.SIGQUIT)
    assert -1 * int(signal.SIGQUIT) == find_links_server.wait()

    assert (
        b"Fetching from https://example.com ..."
        == subprocess.check_output(args=[example_sdist_pex]).strip()
    )
