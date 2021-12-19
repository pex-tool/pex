# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
import sys
from textwrap import dedent

from pex.common import temporary_dir
from pex.interpreter import PythonInterpreter
from pex.pex_info import PexInfo
from pex.testing import (
    PY27,
    PY37,
    PY310,
    ensure_python_interpreter,
    make_env,
    run_pex_command,
    run_simple_pex,
)
from pex.third_party import pkg_resources
from pex.typing import TYPE_CHECKING

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
                "--interpreter-constraint=>=3.5",
                "-o",
                pex_out_path,
            ]
        )
        res.assert_success()
        pex_info = PexInfo.from_pex(pex_out_path)
        assert {">=2.7,<3", ">=3.5"} == set(pex_info.interpreter_constraints)


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
        assert [">3"] == pex_info.interpreter_constraints


def test_interpreter_resolution_with_constraint_option():
    # type: () -> None
    with temporary_dir() as output_dir:
        pex_out_path = os.path.join(output_dir, "pex1.pex")
        res = run_pex_command(
            ["--disable-cache", "--interpreter-constraint=>=2.7,<3", "-o", pex_out_path]
        )
        res.assert_success()
        pex_info = PexInfo.from_pex(pex_out_path)
        assert [">=2.7,<3"] == pex_info.interpreter_constraints


def test_interpreter_resolution_with_multiple_constraint_options():
    # type: () -> None
    with temporary_dir() as output_dir:
        pex_out_path = os.path.join(output_dir, "pex1.pex")
        res = run_pex_command(
            [
                "--disable-cache",
                "--interpreter-constraint=>=2.7,<3",
                # Add a constraint that's impossible to satisfy. Because multiple
                # constraints OR, the interpeter should still resolve to Python 2.7.
                "--interpreter-constraint=>=500",
                "-o",
                pex_out_path,
            ]
        )
        res.assert_success()
        pex_info = PexInfo.from_pex(pex_out_path)
        assert {">=2.7,<3", ">=500"} == set(pex_info.interpreter_constraints)


def test_interpreter_resolution_with_pex_python_path():
    # type: () -> None
    with temporary_dir() as td:
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            # set pex python path
            pex_python_path = ":".join(
                [ensure_python_interpreter(PY27), ensure_python_interpreter(PY37)]
            )
            pexrc.write("PEX_PYTHON_PATH=%s" % pex_python_path)

        # constraints to build pex cleanly; PPP + pex_bootstrapper.py
        # will use these constraints to override sys.executable on pex re-exec
        interpreter_constraint1 = ">3" if sys.version_info[0] == 3 else "<3"
        interpreter_constraint2 = "<3.8" if sys.version_info[0] == 3 else ">=2.7"

        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(
            [
                "--disable-cache",
                "--rcfile=%s" % pexrc_path,
                "--interpreter-constraint=%s,%s"
                % (interpreter_constraint1, interpreter_constraint2),
                "-o",
                pex_out_path,
            ]
        )
        res.assert_success()

        stdin_payload = b"import sys; print(sys.executable); sys.exit(0)"
        stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)

        assert rc == 0
        if sys.version_info[0] == 3:
            assert str(pex_python_path.split(":")[1]).encode() in stdout
        else:
            assert str(pex_python_path.split(":")[0]).encode() in stdout


def test_interpreter_constraints_honored_without_ppp_or_pp(tmpdir):
    # type: (Any) -> None
    # Create a pex with interpreter constraints, but for not the default interpreter in the path.

    py310_path = ensure_python_interpreter(PY310)
    py37_path = ensure_python_interpreter(PY37)

    pex_out_path = os.path.join(str(tmpdir), "pex.pex")
    env = make_env(
        PEX_IGNORE_RCFILES="1",
        PATH=os.pathsep.join(
            [
                os.path.dirname(py37_path),
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
    ppp = ":".join(os.path.dirname(ensure_python_interpreter(py)) for py in (PY27, PY37))
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
            "--interpreter-constraint=>3,<3.8",
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
    assert b"3.7\n" == stdout


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
    with temporary_dir() as td:
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            # set pex python path
            pex_python_path = ":".join(
                [ensure_python_interpreter(PY27), ensure_python_interpreter(PY310)]
            )
            pexrc.write("PEX_PYTHON_PATH=%s" % pex_python_path)

        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(["--disable-cache", "--rcfile=%s" % pexrc_path, "-o", pex_out_path])
        res.assert_success()

        # test that pex bootstrapper selects lowest version interpreter
        # in pex python path (python2.7)
        stdin_payload = b"import sys; print(sys.executable); sys.exit(0)"
        stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)
        assert rc == 0
        assert str(pex_python_path.split(":")[0]).encode() in stdout


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
                    ":".join(os.path.dirname(ensure_python_interpreter(py)) for py in (PY310, PY27))
                )
            )
        )

    pex_out_path = os.path.join(str(tmpdir), "pex.pex")
    res = run_pex_command(["--disable-cache", "--rcfile", pexrc_path, "-o", pex_out_path])
    res.assert_success()

    # test that pex bootstrapper selects lowest version interpreter
    # in pex python path (python2.7)
    stdout, rc = run_simple_pex(
        pex_out_path, args=["-c", "import sys; print('.'.join(map(str, sys.version_info[:2])))"]
    )
    assert rc == 0
    assert b"2.7\n" == stdout


def test_pex_python():
    # type: () -> None
    py2_path_interpreter = ensure_python_interpreter(PY27)
    py3_path_interpreter = ensure_python_interpreter(PY37)
    path = ":".join([os.path.dirname(py2_path_interpreter), os.path.dirname(py3_path_interpreter)])
    env = make_env(PATH=path)
    with temporary_dir() as td:
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            pex_python = ensure_python_interpreter(PY37)
            pexrc.write("PEX_PYTHON=%s" % pex_python)

        # test PEX_PYTHON with valid constraints
        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(
            [
                "--disable-cache",
                "--rcfile=%s" % pexrc_path,
                "--interpreter-constraint=>3,<3.8",
                "-o",
                pex_out_path,
            ],
            env=env,
        )
        res.assert_success()

        stdin_payload = b"import sys; print(sys.executable); sys.exit(0)"
        stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload, env=env)
        assert rc == 0
        correct_interpreter_path = pex_python.encode()
        assert correct_interpreter_path in stdout

        # test PEX_PYTHON with incompatible constraints
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            pex_python = ensure_python_interpreter(PY27)
            pexrc.write("PEX_PYTHON=%s" % pex_python)

        pex_out_path = os.path.join(td, "pex2.pex")
        res = run_pex_command(
            [
                "--disable-cache",
                "--rcfile=%s" % pexrc_path,
                "--interpreter-constraint=>3,<3.8",
                "-o",
                pex_out_path,
            ],
            env=env,
        )
        res.assert_success()

        stdin_payload = b"import sys; print(sys.executable); sys.exit(0)"
        stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload, env=env)
        assert rc == 1
        fail_str = ("Failed to find a compatible PEX_PYTHON={}.".format(pex_python)).encode()
        assert fail_str in stdout

        # test PEX_PYTHON with no constraints
        pex_out_path = os.path.join(td, "pex3.pex")
        res = run_pex_command(
            ["--disable-cache", "--rcfile=%s" % pexrc_path, "-o", pex_out_path], env=env
        )
        res.assert_success()

        stdin_payload = b"import sys; print(sys.executable); sys.exit(0)"
        stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload, env=env)
        assert rc == 0
        correct_interpreter_path = pex_python.encode()
        assert correct_interpreter_path in stdout


def test_interpreter_selection_using_os_environ_for_bootstrap_reexec():
    # type: () -> None
    """This is a test for verifying the proper function of the pex bootstrapper's interpreter
    selection logic and validate a corresponding bugfix.

    More details on the nature of the bug can be found at:
    https://github.com/pantsbuild/pex/pull/441
    """
    with temporary_dir() as td:
        pexrc_path = os.path.join(td, ".pexrc")

        # Select pexrc interpreter versions based on test environment.
        # The parent interpreter is the interpreter we expect the parent pex to
        # execute with. The child interpreter is the interpreter we expect the
        # child pex to execute with.
        if sys.version_info[:2] == (3, 8):
            child_pex_interpreter_version = PY310
        else:
            child_pex_interpreter_version = PY27

        # Write parent pex's pexrc.
        with open(pexrc_path, "w") as pexrc:
            pexrc.write("PEX_PYTHON=%s" % sys.executable)

        # The code below depends on pex.testing which depends on pytest - make sure the built pex gets
        # this dep.
        pytest_dist = pkg_resources.WorkingSet().find(pkg_resources.Requirement.parse("pytest"))

        test_setup_path = os.path.join(td, "setup.py")
        with open(test_setup_path, "w") as fh:
            fh.write(
                dedent(
                    """
                    from setuptools import setup

                    setup(
                        name='tester',
                        version='1.0',
                        description='tests',
                        author='tester',
                        author_email='test@test.com',
                        packages=['testing'],
                        install_requires={install_requires!r}
                    )
                    """.format(
                        install_requires=[str(pytest_dist.as_requirement())]
                    )
                )
            )

        os.mkdir(os.path.join(td, "testing"))
        test_init_path = os.path.join(td, "testing/__init__.py")
        with open(test_init_path, "w") as fh:
            fh.write(
                dedent(
                    '''
                    def tester():
                        from pex.testing import (
                            run_pex_command,
                            run_simple_pex,
                            temporary_dir
                        )
                        import os
                        from textwrap import dedent
                        with temporary_dir() as td:
                            pexrc_path = os.path.join(td, '.pexrc')
                            with open(pexrc_path, 'w') as pexrc:
                                pexrc.write("PEX_PYTHON={}")
                            test_file_path = os.path.join(td, 'build_and_run_child_pex.py')
                            with open(test_file_path, 'w') as fh:
                                fh.write(dedent("""
                                    import sys
                                    print(sys.executable)
                                """))
                            pex_out_path = os.path.join(td, 'child.pex')
                            res = run_pex_command(['--disable-cache',
                                '-o', pex_out_path])
                            stdin_payload = b'import sys; print(sys.executable); sys.exit(0)'
                            stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)
                            print(stdout)
                    '''.format(
                        ensure_python_interpreter(child_pex_interpreter_version)
                    )
                )
            )

        pex_out_path = os.path.join(td, "parent.pex")
        res = run_pex_command(
            ["--disable-cache", "pex", "{}".format(td), "-e", "testing:tester", "-o", pex_out_path]
        )
        res.assert_success()

        stdout, rc = run_simple_pex(pex_out_path)
        assert rc == 0
        # Ensure that child pex used the proper interpreter as specified by its pexrc.
        correct_interpreter_path = ensure_python_interpreter(child_pex_interpreter_version)
        assert correct_interpreter_path in stdout.decode("utf-8")
