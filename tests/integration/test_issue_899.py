# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.interpreter import PythonInterpreter
from pex.pex_info import PexInfo
from pex.testing import PY27, PY310, ensure_python_interpreter, run_pex_command, run_simple_pex
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_top_level_environment_markers(tmpdir):
    # type: (Any) -> None
    python27 = ensure_python_interpreter(PY27)
    python310 = ensure_python_interpreter(PY310)

    pex_file = os.path.join(str(tmpdir), "pex")

    requirement = "subprocess32==3.2.7; python_version<'3'"
    results = run_pex_command(
        args=["--python", python27, "--python", python310, requirement, "-o", pex_file]
    )
    results.assert_success()
    requirements = PexInfo.from_pex(pex_file).requirements
    assert len(requirements) == 1
    assert Requirement.parse(requirement) == Requirement.parse(requirements.pop())

    output, returncode = run_simple_pex(
        pex_file,
        args=["-c", "import subprocess32"],
        interpreter=PythonInterpreter.from_binary(python27),
    )
    assert 0 == returncode

    py310_interpreter = PythonInterpreter.from_binary(python310)

    output, returncode = run_simple_pex(
        pex_file,
        args=["-c", "import subprocess"],
        interpreter=py310_interpreter,
    )
    assert 0 == returncode

    output, returncode = run_simple_pex(
        pex_file,
        args=["-c", "import subprocess32"],
        interpreter=py310_interpreter,
    )
    assert (
        1 == returncode
    ), "Expected subprocess32 to be present in the PEX file but not activated for Python 3."
