import os.path
import subprocess
import sys

from pex.testing import PY38, ensure_python_interpreter, make_env, run_pex_command
from pex.typing import TYPE_CHECKING

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
        # The package script requires Python 3.
        python=sys.executable if sys.version_info[0] >= 3 else ensure_python_interpreter(PY38),
    ).assert_success()
    # The packaged Pex PEX should work with all Pythons we support, including the current test
    # interpreter.
    compiled_deps_dir = str(tmpdir)
    output = subprocess.run(
        args=[sys.executable, pex, "venv", "--scope", "deps", "--compile", compiled_deps_dir],
        env=make_env(PEX_PYTHON=sys.executable, PEX_TOOLS=1),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert (
        "PEXWarning: ignoring compile error NonZeroExit" in output.stderr
    ), "PEXWarning should be generated."
