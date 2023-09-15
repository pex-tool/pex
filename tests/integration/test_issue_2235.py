import os
import subprocess
import sys

import pytest

from pex.compatibility import PY3
from testing import PY38, ensure_python_interpreter


@pytest.mark.skipif(sys.version_info < (3, 8), reason="Flask 2.3.3 requires Python3.8+.")
def test_standard_library_is_included(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    # N.B.: The package script requires Python 3.
    python = sys.executable if PY3 else ensure_python_interpreter(PY38)

    package_script = os.path.join(pex_project_dir, "scripts", "package.py")
    pex_pex = os.path.join(str(tmpdir), "pex")
    subprocess.check_call(args=[python, package_script, "--pex-output-file", pex_pex])

    subprocess.run(
        [
            sys.executable,
            pex_pex,
            "Flask==2.3.3",
            "-o",
            "flask.pex",
            "--venv",
        ],
        check=True,
        env=os.environ,
    )

    output_path = "{}/output.txt".format(tmpdir)

    script = """
import sys
error = ""

try:
    sys.path.append("flask.pex")
    import __pex__
    import flask
except Exception as e:
    error = str(e)

with open("{}", 'w') as f:
    f.write(error)
""".format(
        output_path
    )

    script_path = "{}/script.py".format(tmpdir)
    with open(script_path, "w") as f:
        f.write(script)

    subprocess.run([sys.executable, script_path], check=True, env=os.environ)

    with open(output_path, "r") as f:
        output = f.read()

    if output:
        pytest.fail(f"Test failed with exception: {output}")
