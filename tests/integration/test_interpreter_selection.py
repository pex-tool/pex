# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
from textwrap import dedent

import pytest

from pex.common import safe_open, temporary_dir
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import InterpreterConstraints
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from testing import (
    PY38,
    PY39,
    PY310,
    ensure_python_interpreter,
    make_env,
    run_pex_command,
    run_simple_pex,
)

if TYPE_CHECKING:
    from typing import Any


def test_interpreter_constraints_to_pex_info_py2():
    # type: () -> None
    with temporary_dir() as output_dir:
        # target python 2
        pex_out_path = os.path.join(output_dir, "pex_py2.pex")
        res = run_pex_command(
            [
                "--disable-cache",
                "--interpreter-constraint=>=2.7,<3",
                "--interpreter-constraint=>=3.5,<3.12",
                "-o",
                pex_out_path,
            ]
        )
        res.assert_success()
        pex_info = PexInfo.from_pex(pex_out_path)
        assert (
            InterpreterConstraints.parse(">=2.7,<3", ">=3.5,<3.12")
            == pex_info.interpreter_constraints
        )


def test_interpreter_constraints_to_pex_info_py3():
    # type: () -> None
    py3_interpreter = ensure_python_interpreter(PY310)
    with temporary_dir() as output_dir:
        # target python 3
        pex_out_path = os.path.join(output_dir, "pex_py3.pex")
        res = run_pex_command(
            ["--disable-cache", "--interpreter-constraint=>3", "-o", pex_out_path],
            env=make_env(PATH=os.path.dirname(py3_interpreter)),
        )
        res.assert_success()
        pex_info = PexInfo.from_pex(pex_out_path)
        assert InterpreterConstraints.parse(">3") == pex_info.interpreter_constraints


@pytest.fixture
def satisfiable_interpreter_constraint():
    # type: () -> str
    return "=={major}.{minor}.*".format(major=sys.version_info[0], minor=sys.version_info[1])


def test_interpreter_resolution_with_constraint_option(satisfiable_interpreter_constraint):
    # type: (str) -> None
    with temporary_dir() as output_dir:
        pex_out_path = os.path.join(output_dir, "pex1.pex")
        res = run_pex_command(
            [
                "--disable-cache",
                "--interpreter-constraint",
                satisfiable_interpreter_constraint,
                "-o",
                pex_out_path,
            ]
        )
        res.assert_success()
        pex_info = PexInfo.from_pex(pex_out_path)
        assert (
            InterpreterConstraints.parse(satisfiable_interpreter_constraint)
            == pex_info.interpreter_constraints
        )


def test_interpreter_resolution_with_multiple_constraint_options(
    satisfiable_interpreter_constraint,
):
    # type: (str) -> None
    with temporary_dir() as output_dir:
        pex_out_path = os.path.join(output_dir, "pex1.pex")
        res = run_pex_command(
            [
                "--disable-cache",
                "--interpreter-constraint",
                satisfiable_interpreter_constraint,
                # Add a constraint that's impossible to satisfy. Because multiple
                # constraints OR, the interpreter should still resolve the 1st IC.
                "--interpreter-constraint",
                ">=500",
                "-o",
                pex_out_path,
            ]
        )
        res.assert_success()
        pex_info = PexInfo.from_pex(pex_out_path)
        assert (
            InterpreterConstraints.parse(satisfiable_interpreter_constraint, ">=500")
            == pex_info.interpreter_constraints
        )


def test_interpreter_resolution_with_pex_python_path():
    # type: () -> None

    py38 = ensure_python_interpreter(PY38)
    py39 = ensure_python_interpreter(PY39)

    with temporary_dir() as td:
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            pexrc.write("PEX_PYTHON_PATH={}".format(os.pathsep.join([py38, py39])))

        # constraints to build pex cleanly; PPP + pex_bootstrapper.py
        # will use these constraints to override sys.executable on pex re-exec
        interpreter_constraint = "==3.8.*" if sys.version_info[:2] == (3, 9) else "==3.9.*"

        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(
            [
                "--disable-cache",
                "--rcfile={}".format(pexrc_path),
                "--interpreter-constraint={}".format(interpreter_constraint),
                "-o",
                pex_out_path,
            ]
        )
        res.assert_success()

        stdin_payload = b"import sys; print(sys.executable); sys.exit(0)"
        stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)

        assert rc == 0
        if sys.version_info[:2] == (3, 9):
            assert py38 in stdout.decode("utf-8")
        else:
            assert py39 in stdout.decode("utf-8")


def test_interpreter_constraints_honored_without_ppp_or_pp(tmpdir):
    # type: (Any) -> None
    # Create a pex with interpreter constraints, but for not the default interpreter in the path.

    py310_path = ensure_python_interpreter(PY310)
    py38_path = ensure_python_interpreter(PY38)

    pex_out_path = os.path.join(str(tmpdir), "pex.pex")
    env = make_env(
        PEX_IGNORE_RCFILES="1",
        PATH=os.pathsep.join(
            [
                os.path.dirname(py38_path),
                os.path.dirname(py310_path),
            ]
        ),
    )
    res = run_pex_command(
        ["--disable-cache", "--interpreter-constraint===%s" % PY310, "-o", pex_out_path], env=env
    )
    res.assert_success()

    # We want to try to run that pex with no environment variables set
    stdin_payload = b"import sys; print(sys.executable); sys.exit(0)"

    stdout, rc = run_simple_pex(
        pex_out_path,
        args=["-c", "import sys; print('.'.join(map(str, sys.version_info[:2])))"],
        env=env,
    )
    assert rc == 0

    # If the constraints are honored, it will have run python3.10 and not python3.7
    # Without constraints, we would expect it to use python3.7 as it is the minimum interpreter
    # in the PATH.
    assert b"3.10\n" == stdout


def test_interpreter_resolution_pex_python_path_precedence_over_pex_python(tmpdir):
    # type: (Any) -> None

    pexrc_path = os.path.join(str(tmpdir), ".pexrc")
    ppp = os.pathsep.join(os.path.dirname(ensure_python_interpreter(py)) for py in (PY38, PY39))
    with open(pexrc_path, "w") as pexrc:
        # set both PPP and PP
        pexrc.write(
            dedent(
                """\
                PEX_PYTHON_PATH={ppp}
                PEX_PYTHON={pp}
                """.format(
                    ppp=ppp, pp=ensure_python_interpreter(PY310)
                )
            )
        )

    pex_out_path = os.path.join(str(tmpdir), "pex.pex")
    run_pex_command(
        [
            "--disable-cache",
            "--rcfile",
            pexrc_path,
            "--interpreter-constraint",
            ">=3.8,<3.10",
            "-o",
            pex_out_path,
        ]
    ).assert_success()

    print_python_version_command = [
        "-c",
        "import sys; print('.'.join(map(str, sys.version_info[:2])))",
    ]

    _, rc = run_simple_pex(pex_out_path, print_python_version_command)
    assert rc != 0, (
        "PEX_PYTHON_PATH should trump PEX_PYTHON when PEX_PYTHON is an explicit path to a Python "
        "interpreter that is not on the PEX_PYTHON_PATH and this should lead to failure to select "
        "an interpreter"
    )

    with open(pexrc_path, "w") as pexrc:
        pexrc.write(
            dedent(
                """\
                PEX_PYTHON_PATH={ppp}
                PEX_PYTHON=python
                """.format(
                    ppp=ppp
                )
            )
        )
    stdout, rc = run_simple_pex(pex_out_path, print_python_version_command)
    assert rc == 0
    assert b"3.8\n" == stdout


def test_plain_pex_exec_no_ppp_no_pp_no_constraints():
    # type: () -> None
    with temporary_dir() as td:
        pex_out_path = os.path.join(td, "pex.pex")
        env = make_env(PEX_IGNORE_RCFILES="1")
        res = run_pex_command(["--disable-cache", "-o", pex_out_path], env=env)
        res.assert_success()

        stdin_payload = b"import os, sys; print(sys.executable); sys.exit(0)"
        stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload, env=env)
        assert rc == 0
        assert (
            PythonInterpreter.get().resolve_base_interpreter().binary.encode() in stdout
        ), "Expected the current interpreter to be used when no constraints were supplied."


def test_pex_exec_with_pex_python_path_only():
    # type: () -> None

    py39 = ensure_python_interpreter(PY39)

    with temporary_dir() as td:
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            # set pex python path
            pexrc.write(
                "PEX_PYTHON_PATH={}".format(
                    os.pathsep.join([py39, ensure_python_interpreter(PY310)])
                )
            )

        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(["--disable-cache", "--rcfile=%s" % pexrc_path, "-o", pex_out_path])
        res.assert_success()

        # test that pex bootstrapper selects the lowest version interpreter
        # in pex python path (python3.9)
        stdin_payload = b"import sys; print(sys.executable); sys.exit(0)"
        stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)
        assert rc == 0
        assert py39 in stdout.decode("utf-8")


def test_pex_exec_with_pex_python_path_and_pex_python_but_no_constraints(tmpdir):
    # type: (Any) -> None
    pexrc_path = os.path.join(str(tmpdir), ".pexrc")
    with open(pexrc_path, "w") as pexrc:
        # set both PPP and PP
        pexrc.write(
            dedent(
                """\
                PEX_PYTHON_PATH={}
                PEX_PYTHON=python
                """.format(
                    os.pathsep.join(
                        os.path.dirname(ensure_python_interpreter(py)) for py in (PY310, PY39)
                    )
                )
            )
        )

    pex_out_path = os.path.join(str(tmpdir), "pex.pex")
    res = run_pex_command(["--disable-cache", "--rcfile", pexrc_path, "-o", pex_out_path])
    res.assert_success()

    # test that pex bootstrapper selects the lowest version interpreter
    # in pex python path (python3.9)
    stdout, rc = run_simple_pex(
        pex_out_path, args=["-c", "import sys; print('.'.join(map(str, sys.version_info[:2])))"]
    )
    assert rc == 0
    assert b"3.9\n" == stdout


def test_pex_python():
    # type: () -> None
    py38 = ensure_python_interpreter(PY38)
    py39 = ensure_python_interpreter(PY39)
    env = make_env(PATH=os.pathsep.join([os.path.dirname(py38), os.path.dirname(py39)]))
    with temporary_dir() as td:
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            pexrc.write("PEX_PYTHON={}".format(py38))

        # test PEX_PYTHON with valid constraints
        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(
            [
                "--disable-cache",
                "--rcfile",
                pexrc_path,
                "--interpreter-constraint",
                ">=3.8,<3.10",
                "-o",
                pex_out_path,
            ],
            env=env,
        )
        res.assert_success()

        stdin_payload = b"import sys; print(sys.executable); sys.exit(0)"
        stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload, env=env)
        assert rc == 0
        assert py38 in stdout.decode("utf-8")

        # test PEX_PYTHON with incompatible constraints
        py310 = ensure_python_interpreter(PY310)
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            pexrc.write("PEX_PYTHON={}".format(py310))

        pex_out_path = os.path.join(td, "pex2.pex")
        res = run_pex_command(
            [
                "--disable-cache",
                "--rcfile",
                pexrc_path,
                "--interpreter-constraint",
                ">=3.8,<3.10",
                "-o",
                pex_out_path,
            ],
            env=env,
        )
        res.assert_success()

        stdin_payload = b"import sys; print(sys.executable); sys.exit(0)"
        stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload, env=env)
        assert rc == 1
        assert "Failed to find a compatible PEX_PYTHON={}.".format(py310) in stdout.decode("utf-8")

        # test PEX_PYTHON with no constraints
        pex_out_path = os.path.join(td, "pex3.pex")
        res = run_pex_command(
            ["--disable-cache", "--rcfile", pexrc_path, "-o", pex_out_path], env=env
        )
        res.assert_success()

        stdin_payload = b"import sys; print(sys.executable); sys.exit(0)"
        stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload, env=env)
        assert rc == 0
        assert py310 in stdout.decode("utf-8")


def test_interpreter_selection_using_os_environ_for_bootstrap_reexec(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None
    """This is a test for verifying the proper function of the pex bootstrapper's interpreter
    selection logic and validate a corresponding bugfix.

    More details on the nature of the bug can be found at:
    https://github.com/pex-tool/pex/pull/441
    """
    td = os.path.join(str(tmpdir), "tester_project")
    pexrc_path = os.path.join(td, ".pexrc")

    # Select pexrc interpreter versions based on test environment.
    # The parent interpreter is the interpreter we expect the parent pex to
    # execute with. The child interpreter is the interpreter we expect the
    # child pex to execute with.
    if sys.version_info[:2] == (3, 10):
        child_pex_interpreter_version = PY39
    else:
        child_pex_interpreter_version = PY310

    # Write parent pex's pexrc.
    with safe_open(pexrc_path, "w") as pexrc:
        pexrc.write("PEX_PYTHON={}".format(sys.executable))

    test_setup_path = os.path.join(td, "setup.py")
    with safe_open(test_setup_path, "w") as fh:
        fh.write(
            dedent(
                """
                from setuptools import setup


                setup(
                    name="tester",
                    version="1.0",
                    description="tests",
                    author="tester",
                    author_email="tester@test.com",
                    packages=["tester"],
                )
                """
            )
        )

    test_init_path = os.path.join(td, "tester/__init__.py")
    with safe_open(test_init_path, "w") as fh:
        fh.write(
            dedent(
                """\
                def test_it():
                    import atexit
                    import os
                    import shutil
                    import subprocess
                    import sys
                    import tempfile


                    td = tempfile.mkdtemp()
                    atexit.register(shutil.rmtree, td)

                    pexrc_path = os.path.join(td, ".pexrc")
                    with open(pexrc_path, "w") as pexrc:
                        pexrc.write("PEX_PYTHON={}")

                    pex_out_path = os.path.join(td, "child.pex")
                    subprocess.check_call(
                        [sys.executable, "-mpex", "--disable-cache", "-o", pex_out_path]
                    )
                    process = subprocess.Popen(
                        [sys.executable, pex_out_path, "-c", "import sys; print(sys.executable)"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                    stdout, _ = process.communicate()
                    print(stdout)
                    sys.exit(process.returncode)
                """.format(
                    ensure_python_interpreter(child_pex_interpreter_version)
                )
            )
        )

    pex_out_path = os.path.join(td, "parent.pex")
    res = run_pex_command(
        [
            "--disable-cache",
            pex_project_dir,
            td,
            "-e",
            "tester:test_it",
            "-o",
            pex_out_path,
        ]
    )
    res.assert_success()

    stdout, rc = run_simple_pex(pex_out_path)
    assert rc == 0, stdout
    # Ensure that child pex used the proper interpreter as specified by its pexrc.
    correct_interpreter_path = ensure_python_interpreter(child_pex_interpreter_version)
    assert correct_interpreter_path in stdout.decode("utf-8")
