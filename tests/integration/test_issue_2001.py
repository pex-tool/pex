import os.path
import subprocess
import sys

from pex.typing import TYPE_CHECKING
from testing import make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any


def test_compile_error_as_warning(
    tmpdir,  # type: Any
):
    # type: (...) -> None
    pex = os.path.join(str(tmpdir), "pex.pex")
    run_pex_command(
        args=[
            "--include-tools",
            "aenum==3.1.11",
            "-o",
            pex,
        ],
        python=sys.executable,
    ).assert_success()
    # The packaged Pex PEX should work with all Pythons we support, including the current test
    # interpreter.
    python_version = sys.version_info[0]
    compiled_deps_dir = str(tmpdir)
    process = subprocess.Popen(
        args=[sys.executable, pex, "venv", "--scope", "deps", "--compile", compiled_deps_dir],
        env=make_env(PEX_PYTHON=sys.executable, PEX_TOOLS=1),
        stderr=subprocess.PIPE,
    )
    _, stderr_bytes = process.communicate()
    assert 0 == process.returncode

    stderr_str = stderr_bytes.decode("utf-8")
    if python_version == 2:
        assert not stderr_str, "No PEXWarning should be generated for python2"
    else:
        assert (
            "PEXWarning: ignoring compile error" in stderr_str
        ), "PEXWarning should be generated for python3."
