# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import multiprocessing
import os

from pex.common import temporary_dir
from pex.interpreter import PythonInterpreter
from pex.testing import (
    PY27,
    PY310,
    IntegResults,
    ensure_python_interpreter,
    make_env,
    run_pex_command,
    run_simple_pex,
)
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import List


def test_resolve_local_platform():
    # type: () -> None
    python27 = ensure_python_interpreter(PY27)
    python310 = ensure_python_interpreter(PY310)
    pex_python_path = os.pathsep.join((python27, python310))

    def create_platform_pex(args):
        # type: (List[str]) -> IntegResults
        return run_pex_command(
            args=["--platform", str(PythonInterpreter.from_binary(python310).platform)] + args,
            python=python27,
            env=make_env(PEX_PYTHON_PATH=pex_python_path),
        )

    with temporary_dir() as td:
        pex_file = os.path.join(td, "pex_file")

        # N.B.: We use psutil since only an sdist is available for linux and osx and the distribution
        # has no dependencies.
        args = ["psutil==5.7.0", "-o", pex_file]

        # By default, no --platforms are resolved and so distributions must be available in binary form.
        results = create_platform_pex(args)
        results.assert_failure()

        # If --platform resolution is enabled however, we should be able to find a corresponding local
        # interpreter to perform a full-featured resolve with.
        results = create_platform_pex(["--resolve-local-platforms"] + args)
        results.assert_success()

        output, returncode = run_simple_pex(
            pex=pex_file,
            args=("-c", "import psutil; print(psutil.cpu_count())"),
            interpreter=PythonInterpreter.from_binary(python310),
        )
        assert 0 == returncode
        assert int(output.strip()) >= multiprocessing.cpu_count()
