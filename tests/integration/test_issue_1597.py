# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os.path
import platform

from pex.cli.testing import run_pex3
from pex.interpreter import PythonInterpreter
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.targets import CompletePlatform
from pex.testing import IntegResults, built_wheel, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, List


def build_pex(
    args,  # type: List[str]
    marker='python_full_version == "{python_full_version}"'.format(
        python_full_version=platform.python_version()
    ),  # type: str
):
    # type: (...) -> IntegResults

    with built_wheel(
        name="project_has_python_full_version_marker",
        version="0.1.0",
        install_reqs=["ansicolors==1.1.8; {marker}".format(marker=marker)],
        universal=True,
    ) as wheel:
        return run_pex_command(
            args=["-f", os.path.dirname(wheel), "project_has_python_full_version_marker"] + args,
        )


def assert_expected_dists(pex_file):
    # type: (str) -> None
    assert {
        ProjectName("project_has_python_full_version_marker"): Version("0.1.0"),
        ProjectName("ansicolors"): Version("1.1.8"),
    } == {ProjectName(dist.project_name): Version(dist.version) for dist in PEX(pex_file).resolve()}


def test_platform_complete(
    current_interpreter,  # type: PythonInterpreter
    tmpdir,  # type: Any
):
    # type: (...) -> None

    local_interpreter_pex = os.path.join(str(tmpdir), "local_interpreter.pex")
    build_pex(
        args=["-o", local_interpreter_pex, "--python", current_interpreter.binary]
    ).assert_success()
    assert_expected_dists(local_interpreter_pex)

    # An abbreviated platform does not have the Python interpreter patch version needed to form a
    # `python_full_version` marker environment entry.
    result = build_pex(
        args=["-o", local_interpreter_pex, "--platform", "manylinux_2_35_x86_64-cp-310-cp310"]
    )
    result.assert_failure()
    assert "'python_full_version' does not exist in evaluation environment." in result.error

    complete_platform_pex = os.path.join(str(tmpdir), "complete_platform.pex")
    complete_platform = CompletePlatform.from_interpreter(current_interpreter)
    build_pex(
        args=[
            "-o",
            complete_platform_pex,
            "--complete-platform",
            json.dumps(
                dict(
                    marker_environment=complete_platform.marker_environment.as_dict(),
                    compatible_tags=complete_platform.supported_tags.to_string_list(),
                )
            ),
        ]
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
        args=["-o", complete_platform_from_file_pex, "--complete-platform", platform_file]
    ).assert_success()
    assert_expected_dists(complete_platform_from_file_pex)


def test_platform_abbreviated(
    current_interpreter,  # type: PythonInterpreter
    tmpdir,  # type: Any
):
    # type: (...) -> None

    pex_file = os.path.join(str(tmpdir), "a.pex")

    # An abbreviated platform does not have the Python interpreter patch version needed to form a
    # `python_full_version` marker environment entry.
    result = build_pex(args=["-o", pex_file, "--platform", "manylinux_2_35_x86_64-cp-310-cp310"])
    result.assert_failure()
    assert "'python_full_version' does not exist in evaluation environment." in result.error

    # However, the Platform supplied by a PythonInterpreter (e.g:
    # manylinux_2_35_x86_64-cp-3.10.2-cp310) includes a full version; so it should work.
    current_interpreter_platform = current_interpreter.platform
    assert 3 == len(current_interpreter_platform.version_info)
    build_pex(
        args=["-o", pex_file, "--platform", str(current_interpreter_platform)]
    ).assert_success()
    assert_expected_dists(pex_file)

    # But the Platform supplied by a PythonInterpreter does not keep enough information from the
    # source interpreter to fill in marker environment fields like `platform_version`.
    result = build_pex(
        args=["-o", pex_file, "--platform", str(current_interpreter_platform)],
        marker='platform_version == "#1 SMP PREEMPT Wed, 16 Feb 2022 19:35:18 +0000"',
    )
    result.assert_failure()
    assert "'platform_version' does not exist in evaluation environment." in result.error
