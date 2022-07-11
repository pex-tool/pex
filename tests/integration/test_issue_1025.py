# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import errno
import os
import uuid

import pytest

from pex.common import temporary_dir
from pex.executor import Executor
from pex.interpreter import PythonInterpreter
from pex.testing import PY310, ensure_python_venv, make_env, run_pex_command, run_simple_pex


@pytest.fixture
def create_pth():
    def safe_rm(path):
        try:
            os.unlink(path)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    cleanups = []

    def write_pth(pth_path, sitedir):
        cleanups.append(lambda: safe_rm(pth_path))
        with open(pth_path, "w") as fp:
            fp.write("import site; site.addsitedir({!r})\n".format(sitedir))

    try:
        yield write_pth
    finally:
        for cleanup in cleanups:
            cleanup()


def test_extras_isolation(create_pth):
    python, pip = ensure_python_venv(PY310)
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
