# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import multiprocessing
import os
import subprocess

from pex.interpreter import PythonInterpreter
from pex.typing import TYPE_CHECKING
from testing import PY39, PY310, IntegResults, ensure_python_interpreter, make_env, run_pex_command
from testing.pytest.tmp import Tempdir

if TYPE_CHECKING:
    from typing import List


def test_resolve_local_platform(tmpdir):
    # type: (Tempdir) -> None
    python39 = ensure_python_interpreter(PY39)
    python310 = ensure_python_interpreter(PY310)
    pex_python_path = os.pathsep.join((python39, python310))

    def create_platform_pex(args):
        # type: (List[str]) -> IntegResults
        return run_pex_command(
            args=["--platform", str(PythonInterpreter.from_binary(python310).platform)] + args,
            python=python39,
            env=make_env(PEX_PYTHON_PATH=pex_python_path),
        )

    pex_file = tmpdir.join("pex_file")

    # N.B.: We use psutil since only an sdist is available for linux and osx and the
    # distribution has no dependencies.
    build_args = ["psutil==5.7.0", "-o", pex_file]
    check_args = [python310, pex_file, "-c", "import psutil; print(psutil.cpu_count())"]
    check_env = make_env(PEX_PYTHON_PATH=python310, PEX_VERBOSE=1)

    # By default, no --platforms are resolved and so the yolo build process will produce a wheel
    # using Python 3.9, which is not compatible with Python 3.10.
    create_platform_pex(build_args).assert_success()
    process = subprocess.Popen(check_args, env=check_env, stderr=subprocess.PIPE)
    _, stderr = process.communicate()
    error = stderr.decode("utf-8")
    assert process.returncode != 0, error
    assert (
        "Found 1 distribution for psutil that does not apply:\n"
        "  1.) The wheel tags for psutil 5.7.0 are "
    ) in error

    # If --platform resolution is enabled however, we should be able to find a corresponding
    # local interpreter to perform a full-featured resolve with.
    create_platform_pex(["--resolve-local-platforms"] + build_args).assert_success()
    output = subprocess.check_output(check_args, env=check_env).decode("utf-8")
    assert int(output.strip()) >= multiprocessing.cpu_count()
