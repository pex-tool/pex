# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os.path

from pex.cli.testing import run_pex3
from pex.interpreter import PythonInterpreter
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.targets import CompletePlatform
from pex.testing import IntegResults, built_wheel, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_platform_complete(
    current_interpreter,  # type: PythonInterpreter
    tmpdir,  # type: Any
):
    # type: (...) -> None

    def build_pex(*pex_args):
        # type: (*str) -> IntegResults

        with built_wheel(
            name="project_has_python_full_version_marker",
            version="0.1.0",
            install_reqs=[
                'ansicolors==1.1.8; python_full_version == "{python_full_version}"'.format(
                    python_full_version=current_interpreter.identity.env_markers.python_full_version
                )
            ],
            interpreter=current_interpreter,
        ) as wheel:
            return run_pex_command(
                args=["-f", os.path.dirname(wheel), "project_has_python_full_version_marker"]
                + list(pex_args),
            )

    def assert_expected_dists(pex_file):
        # type: (str) -> None
        assert {
            ProjectName("project_has_python_full_version_marker"): Version("0.1.0"),
            ProjectName("ansicolors"): Version("1.1.8"),
        } == {
            ProjectName(dist.project_name): Version(dist.version)
            for dist in PEX(pex_file).resolve()
        }

    local_interpreter_pex = os.path.join(str(tmpdir), "local_interpreter.pex")
    build_pex("-o", local_interpreter_pex, "--python", current_interpreter.binary).assert_success()
    assert_expected_dists(local_interpreter_pex)

    result = build_pex("-o", local_interpreter_pex, "--platform", str(current_interpreter.platform))
    result.assert_failure()
    assert "'python_full_version' does not exist in evaluation environment." in result.error

    complete_platform_pex = os.path.join(str(tmpdir), "complete_platform.pex")
    complete_platform = CompletePlatform.from_interpreter(current_interpreter)
    build_pex(
        "-o",
        complete_platform_pex,
        "--complete-platform",
        json.dumps(
            dict(
                marker_environment=complete_platform.marker_environment.as_dict(),
                compatible_tags=complete_platform.get_supported_tags().to_string_list(),
            )
        ),
    ).assert_success()
    assert_expected_dists(complete_platform_pex)

    complete_platform_from_file_pex = os.path.join(str(tmpdir), "complete_platform.from_file.pex")
    platform_file = os.path.join(str(tmpdir), "platform.json")
    run_pex3(
        "interpreter",
        "inspect",
        "--markers",
        "--tags",
        "--python",
        current_interpreter.binary,
        "-o",
        platform_file,
    ).assert_success()
    build_pex(
        "-o", complete_platform_from_file_pex, "--complete-platform", platform_file
    ).assert_success()
    assert_expected_dists(complete_platform_from_file_pex)
