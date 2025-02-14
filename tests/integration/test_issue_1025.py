# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import uuid

import pytest

from pex.common import safe_delete, temporary_dir
from pex.executor import Executor
from pex.interpreter import PythonInterpreter
from pex.typing import TYPE_CHECKING
from testing import PY310, ensure_python_venv, make_env, run_pex_command, run_simple_pex

if TYPE_CHECKING:
    from typing import Callable, Iterator


@pytest.fixture
def create_pth():
    # type: () -> Iterator[Callable[[str, str], None]]
    cleanups = []

    def write_pth(
        pth_path,  # type: str
        sitedir,  # type: str
    ):
        # type: (...) -> None
        cleanups.append(lambda: safe_delete(pth_path))
        with open(pth_path, "w") as fp:
            fp.write("import site; site.addsitedir({!r})\n".format(sitedir))

    try:
        yield write_pth
    finally:
        for cleanup in cleanups:
            cleanup()


def test_extras_isolation(create_pth):
    # type: (Callable[[str, str], None]) -> None
    venv = ensure_python_venv(PY310)
    python = venv.interpreter.binary
    pip = venv.bin_path("pip")

    interpreter = PythonInterpreter.from_binary(python)
    _, stdout, _ = interpreter.execute(args=["-c", "import site; print(site.getsitepackages()[0])"])
    with temporary_dir() as tmpdir:
        sitedir = os.path.join(tmpdir, "sitedir")
        Executor.execute(cmd=[pip, "install", "--target", sitedir, "ansicolors==1.1.8"])

        pth_path = os.path.join(stdout.strip(), "issues_1025.{}.pth".format(uuid.uuid4().hex))
        create_pth(pth_path, sitedir)

        pex_file = os.path.join(tmpdir, "isolated.pex")
        results = run_pex_command(args=["-o", pex_file], python=python)
        results.assert_success()

        output, returncode = run_simple_pex(
            pex_file,
            args=["-c", "import colors"],
            interpreter=interpreter,
            env=make_env(PEX_VERBOSE="9"),
        )
        assert returncode != 0, output

        output, returncode = run_simple_pex(
            pex_file,
            args=["-c", "import colors"],
            interpreter=interpreter,
            env=make_env(PEX_VERBOSE="9", PEX_INHERIT_PATH="fallback"),
        )
        assert returncode == 0, output
