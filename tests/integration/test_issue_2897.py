# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import re

from pex.dist_metadata import Requirement
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import InterpreterConstraint
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import LockedRequirement
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.model import Lockfile
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    import attr  # vendor:skip
else:
    from pex.third_party import attr


def normalize_lock_configuration(lock_file):
    # type: (str) -> Lockfile

    lock = json_codec.load(lock_file)
    return attr.evolve(
        lock,
        configuration=attr.evolve(
            lock.configuration,
            universal_target=attr.evolve(
                lock.configuration.universal_target, implementation=None, requires_python=()
            ),
        ),
    )


def test_ics_implementation_conflicting():
    # type: () -> None

    run_pex3(
        "lock",
        "create",
        "--style",
        "universal",
        "--interpreter-constraint",
        "CPython>=3.10,<3.12",
        "--interpreter-constraint",
        "PyPy>=3.9,<3.12",
        "vcrpy==7.0.0",
    ).assert_failure(
        expected_error_re=re.escape(
            "The interpreter constraints for a universal resolve cannot have mixed "
            "implementations with differing specifiers.\n"
            "If you feel you need this support, please comment here: "
            "https://github.com/pex-tool/pex/issues/2897#issuecomment-3256619591\n"
            "Given: CPython<3.12,>=3.10 or PyPy<3.12,>=3.9"
        )
    )

    run_pex3(
        "lock",
        "create",
        "--style",
        "universal",
        "--interpreter-constraint",
        ">=3.10,<3.12",
        "--interpreter-constraint",
        "PyPy>=3.10,<3.12",
        "vcrpy==7.0.0",
    ).assert_failure(
        expected_error_re=re.escape(
            "The interpreter constraints for a universal resolve cannot have mixed implementations "
            "unless they are all explicit and span the full set of Pex supported implementations: "
            "CPython and PyPy.\n"
            "Given: <3.12,>=3.10 or PyPy<3.12,>=3.10"
        )
    )


def test_ics_implementation_covering_specifiers_matching(tmpdir):
    # type: (Tempdir) -> None

    def lock_vcr(
        lock_file,  # type: str
        *extra_args  # type: str
    ):
        # type: (...) -> None
        run_pex3(
            "lock",
            "create",
            "--style",
            "universal",
            "vcrpy==7.0.0",
            "--indent",
            "2",
            "-o",
            lock_file,
            *extra_args
        ).assert_success()

    lock1 = tmpdir.join("lock1.json")
    lock2 = tmpdir.join("lock2.json")
    lock_vcr(
        lock1,
        "--interpreter-constraint",
        "CPython>=3.10,<3.12",
        "--interpreter-constraint",
        "PyPy>=3.10,<3.12",
    )
    lock_vcr(
        lock2,
        "--interpreter-constraint",
        ">=3.10,<3.12",
    )
    assert normalize_lock_configuration(lock1) == normalize_lock_configuration(lock2)

    lock3 = tmpdir.join("lock3.json")
    lock_vcr(
        lock3,
        "--interpreter-constraint",
        "==3.10.*",
        "--interpreter-constraint",
        "==3.11.*",
    )
    assert normalize_lock_configuration(lock2) == normalize_lock_configuration(lock3)


def test_ic_implementation_respected(
    tmpdir,  # type: Tempdir
    py311,  # type: PythonInterpreter
):
    # type: (...) -> None

    lock_file = tmpdir.join("lock.json")

    def assert_vcr_lock(interpreter_constraint):
        # type: (str) -> LockedRequirement

        run_pex3(
            "lock",
            "create",
            "--style",
            "universal",
            "--interpreter-constraint",
            interpreter_constraint,
            "--no-build",
            "vcrpy==7.0.0",
            "-o",
            lock_file,
            "--indent",
            "2",
        ).assert_success()

        lock = json_codec.load(lock_file)
        assert lock.configuration.universal_target is not None
        expected_implementation = InterpreterConstraint.parse(interpreter_constraint).implementation
        assert lock.configuration.universal_target.implementation is expected_implementation

        assert len(lock.locked_resolves) == 1
        locked_resolve = lock.locked_resolves[0]
        locked_requirements_by_project_name = {
            locked_requirement.pin.project_name: locked_requirement
            for locked_requirement in locked_resolve.locked_requirements
        }
        vcrpy = locked_requirements_by_project_name.pop(ProjectName("vcrpy"))
        assert {
            Requirement.parse(req)
            for req in (
                "urllib3; platform_python_implementation != 'PyPy' and python_version >= '3.10'",
                "urllib3<2; platform_python_implementation == 'PyPy'",
                "urllib3<2; python_version < '3.10'",
            )
        }.issubset(vcrpy.requires_dists)
        return locked_requirements_by_project_name.pop(ProjectName("urllib3"))

    pypy_version_ceiling = Version("2")
    urllib3 = assert_vcr_lock("CPython>=3.10,<3.12")
    assert urllib3.pin.version >= pypy_version_ceiling
    run_pex_command(
        args=[
            "--lock",
            lock_file,
            "--",
            "-c",
            "import vcr; print(vcr.__version__)",
        ],
        python=py311.binary,
    ).assert_success(expected_output_re=r"^7\.0\.0$")

    pypy_constraint = "PyPy>=3.10,<3.12"
    if any(
        InterpreterConstraint.matches(pypy_constraint, interpreter)
        for interpreter in PythonInterpreter.iter()
    ):
        urllib3 = assert_vcr_lock(pypy_constraint)
        assert urllib3.pin.version < pypy_version_ceiling
