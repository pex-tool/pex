# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import multiprocessing
import os
import re
import subprocess
from textwrap import dedent

from pex.interpreter import PythonInterpreter
from pex.targets import AbbreviatedPlatform
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

    platform = PythonInterpreter.from_binary(python310).platform
    target = AbbreviatedPlatform.create(platform)

    def create_platform_pex(args):
        # type: (List[str]) -> IntegResults
        return run_pex_command(
            args=["--platform", str(platform)] + args,
            python=python39,
            env=make_env(PEX_PYTHON_PATH=pex_python_path),
        )

    pex_file = tmpdir.join("pex_file")

    # N.B.: We use psutil since only an sdist is available for linux and osx and the
    # distribution has no dependencies.
    build_args = ["psutil==5.7.0", "-o", pex_file]
    check_args = [python310, pex_file, "-c", "import psutil; print(psutil.cpu_count())"]
    check_env = make_env(PEX_PYTHON_PATH=python310)

    # By default, no --platforms are resolved and so the yolo build process will produce a wheel
    # using Python 3.9, which is not compatible with Python 3.10. Since we can't be sure of this,
    # we allow the build but warn it may be incompatible.
    create_platform_pex(build_args).assert_success(
        expected_error_re=dedent(
            r"""
            .* PEXWarning: The resolved distributions for 1 target may not be compatible:
            1: {target} may not be compatible with:
                psutil==5\.7\.0 was requested but 1 incompatible dist was resolved:
                    psutil-5\.7\.0-cp39-cp39-.+\.whl
            .*
            """
        )
        .format(target=re.escape(target.render_description()))
        .strip(),
        re_flags=re.DOTALL | re.MULTILINE,
    )
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
