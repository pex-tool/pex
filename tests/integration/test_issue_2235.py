import os
import subprocess
import sys

import pytest

from pex.typing import TYPE_CHECKING
from testing import run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(sys.version_info < (3, 8), reason="Flask 2.3.3 requires Python3.8+.")
def test_standard_library_is_included(
    tmpdir,  # type: Any
):
    # type: (...) -> None

    built_pex_path = os.path.join(str(tmpdir), "flask.pex")
    run_pex_command(
        args=[
            "Flask==2.3.3",
            "-o",
            built_pex_path,
            "--venv",
        ]
    ).assert_success()

    output_path = os.path.join(str(tmpdir), "output.txt")
    script = """
import sys
error = ""

try:
    sys.path.append("{}")
    import __pex__
    import flask
except Exception as e:
    error = str(e)

with open("{}", 'w') as f:
    f.write(error)
""".format(
        built_pex_path, output_path
    )

    script_path = os.path.join(str(tmpdir), "script.py")
    with open(script_path, "w") as f:
        f.write(script)

    subprocess.check_call([sys.executable, script_path])

    with open(output_path, "r") as f:
        output = f.read()

    if output:
        pytest.fail("Test failed with exception: {}".format(output))
