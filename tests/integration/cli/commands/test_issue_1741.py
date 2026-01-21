# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import json

import pytest

from pex.interpreter import PythonInterpreter
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.lockfile import json_codec
from testing import PY_VER, run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(
    PY_VER < (3, 6), reason="opentelemetry-instrumentation-httpx<0.31 requires python >= 3.6"
)
def test_prereleases(
    tmpdir,  # type: Tempdir
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    constraints_txt = tmpdir.join("constraints.txt")
    with open(constraints_txt, "w") as fp:
        # N.B.: httpx released an incompatible pre-release itself (1.0.dev1) on 7/2/2025.
        # This constraint avoids that.
        print("httpx<1", file=fp)

    lockfile = tmpdir.join("lock")
    run_pex3(
        "lock",
        "create",
        "--constraints",
        constraints_txt,
        "opentelemetry-instrumentation-httpx[instruments]<0.31",
        "--pre",
        "-o",
        lockfile,
        "--indent",
        "2",
    ).assert_success()

    lock = json_codec.load(lockfile)
    assert 1 == len(lock.locked_resolves)
    locked_resolve = lock.locked_resolves[0]
    versions_by_project_name = {
        locked_requirement.pin.project_name: locked_requirement.pin.version
        for locked_requirement in locked_resolve.locked_requirements
    }
    expected_version = versions_by_project_name[ProjectName("opentelemetry-instrumentation-httpx")]
    assert expected_version.parsed_version.is_prerelease

    use_lock_args = [
        "--lock",
        lockfile,
        "--",
        "-c",
        "from opentelemetry.instrumentation.httpx.version import __version__; print(__version__)",
    ]

    # 1st prove this does the wrong thing on prior broken versions of Pex.
    result = run_pex_command(
        args=["pex==2.1.83", "-c", "pex", "--"] + use_lock_args,
        # N.B.: Pex 2.1.88 only works on Python 3.10 and older.
        python=py310.binary if PY_VER > (3, 10) else None,
        quiet=True,
    )
    result.assert_failure()
    assert (
        "Dependency on opentelemetry-instrumentation-httpx not satisfied, 1 incompatible "
        "candidate found:\n"
        "1.) opentelemetry-instrumentation-httpx {version} does not satisfy the following "
        "requirements:\n"
        "    <0.31 (via: opentelemetry-instrumentation-httpx[instruments]<0.31)\n".format(
            version=expected_version
        )
    ) in result.error, result.error

    # Now show it currently works.
    result = run_pex_command(args=use_lock_args)
    result.assert_success()
    assert expected_version == Version(str(result.output.strip())), json.dumps(
        json_codec.as_json_data(lock), indent=2, sort_keys=True
    )
