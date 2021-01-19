# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import errno
import filecmp
import functools
import glob
import json
import multiprocessing
import os
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from contextlib import contextmanager
from textwrap import dedent
from zipfile import ZipFile

import pytest

from pex.common import (
    safe_copy,
    safe_mkdir,
    safe_open,
    safe_rmtree,
    safe_sleep,
    temporary_dir,
    touch,
)
from pex.compatibility import WINDOWS, nested, to_bytes
from pex.executor import Executor
from pex.interpreter import PythonInterpreter
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pex_info import PexInfo
from pex.pip import get_pip
from pex.requirements import LogicalLine, PyPIRequirement, URLFetcher, parse_requirement_file
from pex.testing import (
    IS_PYPY,
    NOT_CPYTHON27,
    NOT_CPYTHON27_OR_OSX,
    NOT_CPYTHON36_OR_LINUX,
    PY27,
    PY35,
    PY36,
    IntegResults,
    WheelBuilder,
    built_wheel,
    ensure_python_interpreter,
    ensure_python_venv,
    get_dep_dist_names_from_pex,
    make_source_dir,
    run_pex_command,
    run_simple_pex,
    run_simple_pex_test,
    temporary_content,
)
from pex.third_party import pkg_resources
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING, cast
from pex.util import DistributionHelper, named_temporary_file
from pex.variables import ENV, unzip_dir, venv_dir

if TYPE_CHECKING:
    from typing import (
        Any,
        Callable,
        ContextManager,
        Dict,
        Iterable,
        Iterator,
        List,
        MutableSet,
        Optional,
        Tuple,
    )


def make_env(**kwargs):
    # type: (**Any) -> Dict[str, str]
    env = os.environ.copy()
    env.update((k, str(v)) for k, v in kwargs.items() if v is not None)
    for k, v in kwargs.items():
        if v is None:
            env.pop(k, None)
    return env


def test_pex_execute():
    # type: () -> None
    body = "print('Hello')"
    _, rc = run_simple_pex_test(body, coverage=True)
    assert rc == 0


def test_pex_raise():
    # type: () -> None
    body = "raise Exception('This will improve coverage.')"
    run_simple_pex_test(body, coverage=True)


def assert_installed_wheels(label, pex_root):
    # type: (str, str) -> None
    assert "installed_wheels" in os.listdir(
        pex_root
    ), "Expected {label} pex root to be populated with buildtime artifacts.".format(label=label)


def test_pex_root_build():
    # type: () -> None
    with nested(temporary_dir(), temporary_dir(), temporary_dir()) as (
        buildtime_pex_root,
        output_dir,
        home,
    ):
        output_path = os.path.join(output_dir, "pex.pex")
        args = [
            "pex",
            "-o",
            output_path,
            "--not-zip-safe",
            "--pex-root={}".format(buildtime_pex_root),
        ]
        results = run_pex_command(args=args, env=make_env(HOME=home, PEX_INTERPRETER="1"))
        results.assert_success()
        assert ["pex.pex"] == os.listdir(output_dir), "Expected built pex file."
        assert [] == os.listdir(home), "Expected empty home dir."
        assert_installed_wheels(label="buildtime", pex_root=buildtime_pex_root)


def test_pex_root_run():
    # type: () -> None
    with nested(temporary_dir(), temporary_dir(), temporary_dir(), temporary_dir()) as (
        buildtime_pex_root,
        runtime_pex_root,
        output_dir,
        home,
    ):
        output_path = os.path.join(output_dir, "pex.pex")
        args = [
            "pex",
            "-o",
            output_path,
            "--not-zip-safe",
            "--pex-root={}".format(buildtime_pex_root),
            "--runtime-pex-root={}".format(runtime_pex_root),
        ]
        results = run_pex_command(args=args, env=make_env(HOME=home, PEX_INTERPRETER="1"))
        results.assert_success()
        assert ["pex.pex"] == os.listdir(output_dir), "Expected built pex file."
        assert [] == os.listdir(home), "Expected empty home dir."

        assert_installed_wheels(label="buildtime", pex_root=buildtime_pex_root)
        safe_mkdir(buildtime_pex_root, clean=True)

        assert [] == os.listdir(
            runtime_pex_root
        ), "Expected runtime pex root to be empty prior to any runs."

        _, rc = run_simple_pex(output_path)
        assert rc == 0
        assert_installed_wheels(label="runtime", pex_root=runtime_pex_root)
        assert [] == os.listdir(
            buildtime_pex_root
        ), "Expected buildtime pex root to be empty after runs using a seperate runtime pex root."


def test_cache_disable():
    # type: () -> None
    with nested(temporary_dir(), temporary_dir(), temporary_dir()) as (td, output_dir, tmp_home):
        output_path = os.path.join(output_dir, "pex.pex")
        args = [
            "pex",
            "-o",
            output_path,
            "--not-zip-safe",
            "--disable-cache",
            "--pex-root={}".format(td),
        ]
        results = run_pex_command(args=args, env=make_env(HOME=tmp_home, PEX_INTERPRETER="1"))
        results.assert_success()
        assert ["pex.pex"] == os.listdir(output_dir), "Expected built pex file."
        assert [] == os.listdir(tmp_home), "Expected empty temp home dir."


def test_pex_interpreter():
    # type: () -> None
    with named_temporary_file() as fp:
        fp.write(b"print('Hello world')")
        fp.flush()

        env = make_env(PEX_INTERPRETER=1)

        so, rc = run_simple_pex_test("", args=(fp.name,), coverage=True, env=env)
        assert so == b"Hello world\n"
        assert rc == 0


def test_pex_repl_cli():
    # type: () -> None
    """Tests the REPL in the context of the pex cli itself."""
    stdin_payload = b"import sys; sys.exit(3)"

    with temporary_dir() as output_dir:
        # Create a temporary pex containing just `requests` with no entrypoint.
        pex_path = os.path.join(output_dir, "pex.pex")
        results = run_pex_command(["requests", "-o", pex_path])
        results.assert_success()

        # Test that the REPL is functional.
        stdout, rc = run_simple_pex(pex_path, stdin=stdin_payload)
        assert rc == 3
        assert b">>>" in stdout


def test_pex_repl_built():
    # type: () -> None
    """Tests the REPL in the context of a built pex."""
    stdin_payload = b"import requests; import sys; sys.exit(3)"

    with temporary_dir() as output_dir:
        # Create a temporary pex containing just `requests` with no entrypoint.
        pex_path = os.path.join(output_dir, "requests.pex")
        results = run_pex_command(["--disable-cache", "requests", "-o", pex_path])
        results.assert_success()

        # Test that the REPL is functional.
        stdout, rc = run_simple_pex(pex_path, stdin=stdin_payload)
        assert rc == 3
        assert b">>>" in stdout


@pytest.mark.skipif(WINDOWS, reason="No symlinks on windows")
def test_pex_python_symlink():
    # type: () -> None
    with temporary_dir() as td:
        symlink_path = os.path.join(td, "python-symlink")
        os.symlink(sys.executable, symlink_path)
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            pexrc.write("PEX_PYTHON=%s" % symlink_path)

        body = "print('Hello')"
        _, rc = run_simple_pex_test(body, coverage=True, env=make_env(HOME=td))
        assert rc == 0


def test_entry_point_exit_code():
    # type: () -> None
    setup_py = dedent(
        """
        from setuptools import setup

        setup(
            name='my_app',
            version='0.0.0',
            zip_safe=True,
            packages=[''],
            entry_points={'console_scripts': ['my_app = my_app:do_something']},
        )
        """
    )

    error_msg = "setuptools expects this to exit non-zero"

    my_app = dedent(
        """
        def do_something():
          return '%s'
  """
        % error_msg
    )

    with temporary_content({"setup.py": setup_py, "my_app.py": my_app}) as project_dir:
        installer = WheelBuilder(project_dir)
        dist = installer.bdist()
        so, rc = run_simple_pex_test("", env=make_env(PEX_SCRIPT="my_app"), dists=[dist])
        assert so.decode("utf-8").strip() == error_msg
        assert rc == 1


# TODO: https://github.com/pantsbuild/pex/issues/479
@pytest.mark.skipif(
    NOT_CPYTHON36_OR_LINUX, reason="inherits linux abi on linux w/ no backing packages"
)
def test_pex_multi_resolve():
    # type: () -> None
    """Tests multi-interpreter + multi-platform resolution."""
    with temporary_dir() as output_dir:
        pex_path = os.path.join(output_dir, "pex.pex")
        results = run_pex_command(
            [
                "--disable-cache",
                "lxml==3.8.0",
                "--no-build",
                "--platform=linux-x86_64",
                "--platform=macosx-10.6-x86_64",
                "--python=python2.7",
                "--python=python3.6",
                "-o",
                pex_path,
            ]
        )
        results.assert_success()

        included_dists = get_dep_dist_names_from_pex(pex_path, "lxml")
        assert len(included_dists) == 4
        for dist_substr in ("-cp27-", "-cp36-", "-manylinux1_x86_64", "-macosx_"):
            assert any(dist_substr in f for f in included_dists)


@pytest.mark.xfail(reason="See https://github.com/pantsbuild/pants/issues/4682")
def test_pex_re_exec_failure():
    # type: () -> None
    with temporary_dir() as output_dir:

        # create 2 pex files for PEX_PATH
        pex1_path = os.path.join(output_dir, "pex1.pex")
        res1 = run_pex_command(["--disable-cache", "requests", "-o", pex1_path])
        res1.assert_success()
        pex2_path = os.path.join(output_dir, "pex2.pex")
        res2 = run_pex_command(["--disable-cache", "flask", "-o", pex2_path])
        res2.assert_success()
        pex_path = ":".join(os.path.join(output_dir, name) for name in ("pex1.pex", "pex2.pex"))

        # create test file test.py that attmepts to import modules from pex1/pex2
        test_file_path = os.path.join(output_dir, "test.py")
        with open(test_file_path, "w") as fh:
            fh.write(
                dedent(
                    """
                    import requests
                    import flask
                    import sys
                    import os
                    import subprocess
                    if 'RAN_ONCE' in os.environ::
                        print('Hello world')
                    else:
                        env = os.environ.copy()
                        env['RAN_ONCE'] = '1'
                        subprocess.call([sys.executable] + sys.argv, env=env)
                        sys.exit()
                    """
                )
            )

        # set up env for pex build with PEX_PATH in the environment
        env = make_env(PEX_PATH=pex_path)

        # build composite pex of pex1/pex1
        pex_out_path = os.path.join(output_dir, "out.pex")
        run_pex_command(["--disable-cache", "wheel", "-o", pex_out_path])

        # run test.py with composite env
        stdout, rc = run_simple_pex(pex_out_path, [test_file_path], env=env)

        assert rc == 0
        assert stdout == b"Hello world\n"


def test_pex_path_arg():
    # type: () -> None
    with temporary_dir() as output_dir:

        # create 2 pex files for PEX_PATH
        pex1_path = os.path.join(output_dir, "pex1.pex")
        res1 = run_pex_command(["--disable-cache", "requests", "-o", pex1_path])
        res1.assert_success()
        pex2_path = os.path.join(output_dir, "pex2.pex")
        res2 = run_pex_command(["--disable-cache", "flask", "-o", pex2_path])
        res2.assert_success()
        pex_path = ":".join(os.path.join(output_dir, name) for name in ("pex1.pex", "pex2.pex"))

        # parameterize the pex arg for test.py
        pex_out_path = os.path.join(output_dir, "out.pex")
        # create test file test.py that attempts to import modules from pex1/pex2
        test_file_path = os.path.join(output_dir, "test.py")
        with open(test_file_path, "w") as fh:
            fh.write(
                dedent(
                    """
                    import requests
                    import flask
                    import sys
                    import os
                    import subprocess
                    if 'RAN_ONCE' in os.environ:
                        print('Success!')
                    else:
                        env = os.environ.copy()
                        env['RAN_ONCE'] = '1'
                        subprocess.call([sys.executable] + ['%s'] + sys.argv, env=env)
                        sys.exit()
                    """
                    % pex_out_path
                )
            )

        # build out.pex composed from pex1/pex1
        run_pex_command(
            ["--disable-cache", "--pex-path={}".format(pex_path), "wheel", "-o", pex_out_path]
        )

        # run test.py with composite env
        stdout, rc = run_simple_pex(pex_out_path, [test_file_path])
        assert rc == 0
        assert stdout == b"Success!\n"


def test_pex_path_in_pex_info_and_env():
    # type: () -> None
    with temporary_dir() as output_dir:

        # create 2 pex files for PEX-INFO pex_path
        pex1_path = os.path.join(output_dir, "pex1.pex")
        res1 = run_pex_command(["--disable-cache", "requests", "-o", pex1_path])
        res1.assert_success()
        pex2_path = os.path.join(output_dir, "pex2.pex")
        res2 = run_pex_command(["--disable-cache", "flask", "-o", pex2_path])
        res2.assert_success()
        pex_path = ":".join(os.path.join(output_dir, name) for name in ("pex1.pex", "pex2.pex"))

        # create a pex for environment PEX_PATH
        pex3_path = os.path.join(output_dir, "pex3.pex")
        res3 = run_pex_command(["--disable-cache", "wheel", "-o", pex3_path])
        res3.assert_success()
        env_pex_path = os.path.join(output_dir, "pex3.pex")

        # parameterize the pex arg for test.py
        pex_out_path = os.path.join(output_dir, "out.pex")
        # create test file test.py that attempts to import modules from pex1/pex2
        test_file_path = os.path.join(output_dir, "test.py")
        with open(test_file_path, "w") as fh:
            fh.write(
                dedent(
                    """
                    import requests
                    import flask
                    import wheel
                    import sys
                    import os
                    import subprocess
                    print('Success!')
                    """
                )
            )

        # build out.pex composed from pex1/pex1
        run_pex_command(["--disable-cache", "--pex-path={}".format(pex_path), "-o", pex_out_path])

        # load secondary PEX_PATH
        env = make_env(PEX_PATH=env_pex_path)

        # run test.py with composite env
        stdout, rc = run_simple_pex(pex_out_path, [test_file_path], env=env)
        assert rc == 0
        assert stdout == b"Success!\n"


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
    py3_interpreter = ensure_python_interpreter(PY36)
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
        assert pex_info.build_properties["version"][0] < 3


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
        assert pex_info.build_properties["version"][0] < 3


def test_interpreter_resolution_with_pex_python_path():
    # type: () -> None
    with temporary_dir() as td:
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            # set pex python path
            pex_python_path = ":".join(
                [ensure_python_interpreter(PY27), ensure_python_interpreter(PY36)]
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


def test_interpreter_constraints_honored_without_ppp_or_pp():
    # type: () -> None
    # Create a pex with interpreter constraints, but for not the default interpreter in the path.
    with temporary_dir() as td:
        py36_path = ensure_python_interpreter(PY36)
        py35_path = ensure_python_interpreter(PY35)

        pex_out_path = os.path.join(td, "pex.pex")
        env = make_env(
            PEX_IGNORE_RCFILES="1",
            PATH=os.pathsep.join(
                [
                    os.path.dirname(py35_path),
                    os.path.dirname(py36_path),
                ]
            ),
        )
        res = run_pex_command(
            ["--disable-cache", "--interpreter-constraint===%s" % PY36, "-o", pex_out_path], env=env
        )
        res.assert_success()

        # We want to try to run that pex with no environment variables set
        stdin_payload = b"import sys; print(sys.executable); sys.exit(0)"

        stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload, env=env)
        assert rc == 0

        # If the constraints are honored, it will have run python3.6 and not python3.5
        # Without constraints, we would expect it to use python3.5 as it is the minimum interpreter
        # in the PATH.
        assert str(py36_path).encode() in stdout


def test_interpreter_resolution_pex_python_path_precedence_over_pex_python():
    # type: () -> None
    with temporary_dir() as td:
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            # set both PPP and PP
            pex_python_path = ":".join(
                [ensure_python_interpreter(PY27), ensure_python_interpreter(PY36)]
            )
            pexrc.write("PEX_PYTHON_PATH=%s\n" % pex_python_path)
            pex_python = "/path/to/some/python"
            pexrc.write("PEX_PYTHON=%s" % pex_python)

        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(
            [
                "--disable-cache",
                "--rcfile=%s" % pexrc_path,
                "--interpreter-constraint=>3,<3.8",
                "-o",
                pex_out_path,
            ]
        )
        res.assert_success()

        stdin_payload = b"import sys; print(sys.executable); sys.exit(0)"
        stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)
        assert rc == 0
        correct_interpreter_path = pex_python_path.split(":")[1].encode()
        assert correct_interpreter_path in stdout


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
                [ensure_python_interpreter(PY27), ensure_python_interpreter(PY36)]
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


def test_pex_exec_with_pex_python_path_and_pex_python_but_no_constraints():
    # type: () -> None
    with temporary_dir() as td:
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            # set both PPP and PP
            pex_python_path = ":".join(
                [ensure_python_interpreter(PY27), ensure_python_interpreter(PY36)]
            )
            pexrc.write("PEX_PYTHON_PATH=%s\n" % pex_python_path)
            pex_python = "/path/to/some/python"
            pexrc.write("PEX_PYTHON=%s" % pex_python)

        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(["--disable-cache", "--rcfile=%s" % pexrc_path, "-o", pex_out_path])
        res.assert_success()

        # test that pex bootstrapper selects lowest version interpreter
        # in pex python path (python2.7)
        stdin_payload = b"import sys; print(sys.executable); sys.exit(0)"
        stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)
        assert rc == 0
        assert str(pex_python_path.split(":")[0]).encode() in stdout


def test_pex_python():
    # type: () -> None
    py2_path_interpreter = ensure_python_interpreter(PY27)
    py3_path_interpreter = ensure_python_interpreter(PY36)
    path = ":".join([os.path.dirname(py2_path_interpreter), os.path.dirname(py3_path_interpreter)])
    env = make_env(PATH=path)
    with temporary_dir() as td:
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            pex_python = ensure_python_interpreter(PY36)
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


def test_entry_point_targeting():
    # type: () -> None
    """Test bugfix for https://github.com/pantsbuild/pex/issues/434."""
    with temporary_dir() as td:
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            pex_python = ensure_python_interpreter(PY36)
            pexrc.write("PEX_PYTHON=%s" % pex_python)

        # test pex with entry point
        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(["--disable-cache", "autopep8", "-e", "autopep8", "-o", pex_out_path])
        res.assert_success()

        stdout, rc = run_simple_pex(pex_out_path)
        assert "usage: autopep8".encode() in stdout


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
        if (sys.version_info[0], sys.version_info[1]) == (3, 6):
            child_pex_interpreter_version = PY36
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


def test_inherit_path_fallback():
    # type: () -> None
    inherit_path("=fallback")


def test_inherit_path_backwards_compatibility():
    # type: () -> None
    inherit_path("")


def test_inherit_path_prefer():
    # type: () -> None
    inherit_path("=prefer")


def inherit_path(inherit_path):
    # type: (str) -> None
    with temporary_dir() as output_dir:
        exe = os.path.join(output_dir, "exe.py")
        body = "import sys ; print('\\n'.join(sys.path))"
        with open(exe, "w") as f:
            f.write(body)

        pex_path = os.path.join(output_dir, "pex.pex")
        results = run_pex_command(
            [
                "--disable-cache",
                "msgpack_python",
                "--inherit-path{}".format(inherit_path),
                "-o",
                pex_path,
            ]
        )

        results.assert_success()

        env = make_env(PYTHONPATH="/doesnotexist")
        stdout, rc = run_simple_pex(
            pex_path,
            args=(exe,),
            env=env,
        )
        assert rc == 0

        stdout_lines = stdout.decode().split("\n")
        requests_paths = tuple(i for i, l in enumerate(stdout_lines) if "msgpack_python" in l)
        sys_paths = tuple(i for i, l in enumerate(stdout_lines) if "doesnotexist" in l)
        assert len(requests_paths) == 1
        assert len(sys_paths) == 1

        if inherit_path == "=fallback":
            assert requests_paths[0] < sys_paths[0]
        else:
            assert requests_paths[0] > sys_paths[0]


def test_pex_multi_resolve_2():
    # type: () -> None
    """Tests multi-interpreter + multi-platform resolution using extended platform notation."""
    with temporary_dir() as output_dir:
        pex_path = os.path.join(output_dir, "pex.pex")
        results = run_pex_command(
            [
                "--disable-cache",
                "lxml==3.8.0",
                "--no-build",
                "--platform=linux-x86_64-cp-36-m",
                "--platform=linux-x86_64-cp-27-m",
                "--platform=macosx-10.6-x86_64-cp-36-m",
                "--platform=macosx-10.6-x86_64-cp-27-m",
                "-o",
                pex_path,
            ]
        )
        results.assert_success()

        included_dists = get_dep_dist_names_from_pex(pex_path, "lxml")
        assert len(included_dists) == 4
        for dist_substr in ("-cp27-", "-cp36-", "-manylinux1_x86_64", "-macosx_"):
            assert any(
                dist_substr in f for f in included_dists
            ), "{} was not found in wheel".format(dist_substr)


if TYPE_CHECKING:
    TestResolveFn = Callable[[str, str, str, str, Optional[str]], None]
    EnsureFailureFn = Callable[[str, str, str, str], None]


@contextmanager
def pex_manylinux_and_tag_selection_context():
    # type: () -> Iterator[Tuple[TestResolveFn, EnsureFailureFn]]
    with temporary_dir() as output_dir:

        def do_resolve(req_name, req_version, platform, extra_flags=None):
            # type: (str, str, str, Optional[str]) -> Tuple[str, IntegResults]
            extra_flags = extra_flags or ""
            pex_path = os.path.join(output_dir, "test.pex")
            results = run_pex_command(
                [
                    "--disable-cache",
                    "--no-build",
                    "%s==%s" % (req_name, req_version),
                    "--platform=%s" % platform,
                    "-o",
                    pex_path,
                ]
                + extra_flags.split()
            )
            return pex_path, results

        def test_resolve(req_name, req_version, platform, substr, extra_flags=None):
            # type: (str, str, str, str, Optional[str]) -> None
            pex_path, results = do_resolve(req_name, req_version, platform, extra_flags)
            results.assert_success()
            included_dists = get_dep_dist_names_from_pex(pex_path, req_name.replace("-", "_"))
            assert any(substr in d for d in included_dists), "couldnt find {} in {}".format(
                substr, included_dists
            )

        def ensure_failure(req_name, req_version, platform, extra_flags):
            # type: (str, str, str, str) -> None
            pex_path, results = do_resolve(req_name, req_version, platform, extra_flags)
            results.assert_failure()

        yield test_resolve, ensure_failure


def test_pex_manylinux_and_tag_selection_linux_msgpack():
    # type: () -> None
    """Tests resolver manylinux support and tag targeting."""
    with pex_manylinux_and_tag_selection_context() as (test_resolve, ensure_failure):
        msgpack, msgpack_ver = "msgpack-python", "0.4.7"
        test_msgpack = functools.partial(test_resolve, msgpack, msgpack_ver)

        # Exclude 3.3, >=3.6 because no wheels exist for these versions on pypi.
        current_version = sys.version_info[:2]
        if current_version != (3, 3) and current_version < (3, 6):
            ver = "{}{}".format(*current_version)
            test_msgpack(
                "linux-x86_64-cp-{}-m".format(ver),
                "msgpack_python-0.4.7-cp{ver}-cp{ver}m-manylinux1_x86_64.whl".format(ver=ver),
            )

        test_msgpack(
            "linux-x86_64-cp-27-m", "msgpack_python-0.4.7-cp27-cp27m-manylinux1_x86_64.whl"
        )
        test_msgpack(
            "linux-x86_64-cp-27-mu", "msgpack_python-0.4.7-cp27-cp27mu-manylinux1_x86_64.whl"
        )
        test_msgpack("linux-i686-cp-27-m", "msgpack_python-0.4.7-cp27-cp27m-manylinux1_i686.whl")
        test_msgpack("linux-i686-cp-27-mu", "msgpack_python-0.4.7-cp27-cp27mu-manylinux1_i686.whl")
        test_msgpack(
            "linux-x86_64-cp-27-mu", "msgpack_python-0.4.7-cp27-cp27mu-manylinux1_x86_64.whl"
        )
        test_msgpack(
            "linux-x86_64-cp-34-m", "msgpack_python-0.4.7-cp34-cp34m-manylinux1_x86_64.whl"
        )
        test_msgpack(
            "linux-x86_64-cp-35-m", "msgpack_python-0.4.7-cp35-cp35m-manylinux1_x86_64.whl"
        )

        ensure_failure(msgpack, msgpack_ver, "linux-x86_64", "--no-manylinux")


def test_pex_manylinux_and_tag_selection_lxml_osx():
    # type: () -> None
    with pex_manylinux_and_tag_selection_context() as (test_resolve, ensure_failure):
        test_resolve(
            "lxml", "3.8.0", "macosx-10.6-x86_64-cp-27-m", "lxml-3.8.0-cp27-cp27m-macosx", None
        )
        test_resolve(
            "lxml", "3.8.0", "macosx-10.6-x86_64-cp-36-m", "lxml-3.8.0-cp36-cp36m-macosx", None
        )


@pytest.mark.skipif(NOT_CPYTHON27_OR_OSX, reason="Relies on a pre-built wheel for linux 2.7")
def test_pex_manylinux_runtime():
    # type: () -> None
    """Tests resolver manylinux support and runtime resolution (and --platform=current)."""
    test_stub = dedent(
        """
        import msgpack
        print(msgpack.unpackb(msgpack.packb([1, 2, 3])))
        """
    )

    with temporary_content({"tester.py": test_stub}) as output_dir:
        pex_path = os.path.join(output_dir, "test.pex")
        tester_path = os.path.join(output_dir, "tester.py")
        results = run_pex_command(
            [
                "--disable-cache",
                "--no-build",
                "msgpack-python==0.4.7",
                "--platform=current",
                "-o",
                pex_path,
            ]
        )
        results.assert_success()

        out = subprocess.check_output([pex_path, tester_path])
        assert out.strip() == b"[1, 2, 3]"


def test_pex_exit_code_propagation():
    # type: () -> None
    """Tests exit code propagation."""
    test_stub = dedent(
        """
        def test_fail():
            assert False
        """
    )

    with temporary_content({"tester.py": test_stub}) as output_dir:
        pex_path = os.path.join(output_dir, "test.pex")
        tester_path = os.path.join(output_dir, "tester.py")
        results = run_pex_command(["pytest==3.9.1", "-e", "pytest:main", "-o", pex_path])
        results.assert_success()

        assert subprocess.call([pex_path, os.path.realpath(tester_path)]) == 1


@pytest.mark.skipif(NOT_CPYTHON27, reason="Tests environment markers that select for python 2.7.")
def test_ipython_appnope_env_markers():
    # type: () -> None
    res = run_pex_command(["--disable-cache", "ipython==5.8.0", "-c", "ipython", "--", "--version"])
    res.assert_success()


def test_cross_platform_abi_targeting_behavior_exact():
    # type: () -> None
    with temporary_dir() as td:
        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(
            [
                "--disable-cache",
                "--no-pypi",
                "--platform=linux-x86_64-cp-27-mu",
                "--find-links=tests/example_packages/",
                "MarkupSafe==1.0",
                "-o",
                pex_out_path,
            ]
        )
        res.assert_success()


def test_pex_source_bundling():
    # type: () -> None
    with temporary_dir() as output_dir:
        with temporary_dir() as input_dir:
            with open(os.path.join(input_dir, "exe.py"), "w") as fh:
                fh.write(
                    dedent(
                        """
                        print('hello')
                        """
                    )
                )

            pex_path = os.path.join(output_dir, "pex1.pex")
            res = run_pex_command(
                [
                    "-o",
                    pex_path,
                    "-D",
                    input_dir,
                    "-e",
                    "exe",
                ]
            )
            res.assert_success()

            stdout, rc = run_simple_pex(pex_path)

            assert rc == 0
            assert stdout == b"hello\n"


def test_pex_source_bundling_pep420():
    # type: () -> None
    with temporary_dir() as output_dir:
        with temporary_dir() as input_dir:
            with safe_open(os.path.join(input_dir, "a/b/c.py"), "w") as fh:
                fh.write("GREETING = 'hello'")

            with open(os.path.join(input_dir, "exe.py"), "w") as fh:
                fh.write(
                    dedent(
                        """
                        from a.b.c import GREETING

                        print(GREETING)
                        """
                    )
                )

            pex_path = os.path.join(output_dir, "pex1.pex")
            py36 = ensure_python_interpreter(PY36)
            res = run_pex_command(["-o", pex_path, "-D", input_dir, "-e", "exe"], python=py36)
            res.assert_success()

            stdout, rc = run_simple_pex(pex_path, interpreter=PythonInterpreter.from_binary(py36))

            assert rc == 0
            assert stdout == b"hello\n"


def test_pex_resource_bundling():
    # type: () -> None
    with temporary_dir() as output_dir:
        with temporary_dir() as input_dir, temporary_dir() as resources_input_dir:
            with open(os.path.join(resources_input_dir, "greeting"), "w") as fh:
                fh.write("hello")
            pex_path = os.path.join(output_dir, "pex1.pex")

            with open(os.path.join(input_dir, "exe.py"), "w") as fh:
                fh.write(
                    dedent(
                        """
                        import pkg_resources
                        print(pkg_resources.resource_string('__main__', 'greeting').decode('utf-8'))
                        """
                    )
                )

            res = run_pex_command(
                [
                    "-o",
                    pex_path,
                    "-D",
                    input_dir,
                    "-R",
                    resources_input_dir,
                    "-e",
                    "exe",
                    "setuptools==17.0",
                ]
            )
            res.assert_success()

            stdout, rc = run_simple_pex(pex_path)

            assert rc == 0
            assert stdout == b"hello\n"


def test_entry_point_verification_3rdparty():
    # type: () -> None
    with temporary_dir() as td:
        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(
            ["Pillow==5.2.0", "-e", "PIL:Image", "-o", pex_out_path, "--validate-entry-point"]
        )
        res.assert_success()


def test_invalid_entry_point_verification_3rdparty():
    # type: () -> None
    with temporary_dir() as td:
        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(
            ["Pillow==5.2.0", "-e", "PIL:invalid", "-o", pex_out_path, "--validate-entry-point"]
        )
        res.assert_failure()


def test_multiplatform_entrypoint():
    # type: () -> None
    with temporary_dir() as td:
        pex_out_path = os.path.join(td, "p537.pex")
        interpreter = ensure_python_interpreter(PY36)
        res = run_pex_command(
            [
                "p537==1.0.3",
                "--no-build",
                "--python={}".format(interpreter),
                "--python-shebang=#!{}".format(interpreter),
                "--platform=linux-x86_64-cp-36-m",
                "--platform=macosx-10.13-x86_64-cp-36-m",
                "-c",
                "p537",
                "-o",
                pex_out_path,
                "--validate-entry-point",
            ]
        )
        res.assert_success()

        greeting = subprocess.check_output([pex_out_path])
        assert b"Hello World!" == greeting.strip()


def test_pex_console_script_custom_setuptools_useable():
    # type: () -> None
    setup_py = dedent(
        """
        from setuptools import setup

        setup(
            name='my_app',
            version='0.0.0',
            zip_safe=True,
            packages=[''],
            install_requires=['setuptools==36.2.7'],
            entry_points={'console_scripts': ['my_app_function = my_app:do_something']},
        )
  """
    )

    my_app = dedent(
        """
        import sys

        def do_something():
            try:
                from setuptools.sandbox import run_setup
                return 0
            except:
                return 1
  """
    )

    with temporary_content({"setup.py": setup_py, "my_app.py": my_app}) as project_dir:
        with temporary_dir() as out:
            pex = os.path.join(out, "pex.pex")
            pex_command = [
                "--validate-entry-point",
                "-c",
                "my_app_function",
                project_dir,
                "-o",
                pex,
            ]
            results = run_pex_command(pex_command)
            results.assert_success()

            stdout, rc = run_simple_pex(pex, env=make_env(PEX_VERBOSE=1))
            assert rc == 0, stdout


@contextmanager
def pex_with_no_entrypoints():
    # type: () -> Iterator[Tuple[str, bytes, str]]
    with temporary_dir() as out:
        pex = os.path.join(out, "pex.pex")
        run_pex_command(["setuptools==36.2.7", "-o", pex])
        test_script = b"from setuptools.sandbox import run_setup; print(str(run_setup))"
        yield pex, test_script, out


def test_pex_interpreter_execute_custom_setuptools_useable():
    # type: () -> None
    with pex_with_no_entrypoints() as (pex, test_script, out):
        script = os.path.join(out, "script.py")
        with open(script, "wb") as fp:
            fp.write(test_script)
        stdout, rc = run_simple_pex(pex, args=(script,), env=make_env(PEX_VERBOSE=1))
        assert rc == 0, stdout


def test_pex_interpreter_interact_custom_setuptools_useable():
    # type: () -> None
    with pex_with_no_entrypoints() as (pex, test_script, _):
        stdout, rc = run_simple_pex(pex, env=make_env(PEX_VERBOSE=1), stdin=test_script)
        assert rc == 0, stdout


def test_setup_python():
    # type: () -> None
    interpreter = ensure_python_interpreter(PY27)
    with temporary_dir() as out:
        pex = os.path.join(out, "pex.pex")
        results = run_pex_command(
            ["jsonschema==2.6.0", "--disable-cache", "--python={}".format(interpreter), "-o", pex]
        )
        results.assert_success()
        subprocess.check_call([pex, "-c", "import jsonschema"])


def test_setup_interpreter_constraint():
    # type: () -> None
    interpreter = ensure_python_interpreter(PY27)
    with temporary_dir() as out:
        pex = os.path.join(out, "pex.pex")
        env = make_env(
            PEX_IGNORE_RCFILES="1",
            PATH=os.path.dirname(interpreter),
        )
        results = run_pex_command(
            [
                "jsonschema==2.6.0",
                "--disable-cache",
                "--interpreter-constraint=CPython=={}".format(PY27),
                "-o",
                pex,
            ],
            env=env,
        )
        results.assert_success()

        stdout, rc = run_simple_pex(pex, env=env, stdin=b"import jsonschema")
        assert rc == 0


def test_setup_python_path():
    # type: () -> None
    """Check that `--python-path` is used rather than the default $PATH."""
    py27_interpreter_dir = os.path.dirname(ensure_python_interpreter(PY27))
    py36_interpreter_dir = os.path.dirname(ensure_python_interpreter(PY36))
    with temporary_dir() as out:
        pex = os.path.join(out, "pex.pex")
        # Even though we set $PATH="", we still expect for both interpreters to be used when
        # building the PEX. Note that `more-itertools` has a distinct Py2 and Py3 wheel.
        results = run_pex_command(
            [
                "more-itertools==5.0.0",
                "--disable-cache",
                "--interpreter-constraint=CPython=={}".format(PY27),
                "--interpreter-constraint=CPython=={}".format(PY36),
                "--python-path={}".format(
                    os.pathsep.join([py27_interpreter_dir, py36_interpreter_dir])
                ),
                "-o",
                pex,
            ],
            env=make_env(PEX_IGNORE_RCFILES="1", PATH=""),
        )
        results.assert_success()

        py27_env = make_env(PEX_IGNORE_RCFILES="1", PATH=py27_interpreter_dir)
        stdout, rc = run_simple_pex(
            pex, env=py27_env, stdin=b"import more_itertools, sys; print(sys.version_info[:2])"
        )
        assert rc == 0
        assert b"(2, 7)" in stdout

        py36_env = make_env(PEX_IGNORE_RCFILES="1", PATH=py36_interpreter_dir)
        stdout, rc = run_simple_pex(
            pex, env=py36_env, stdin=b"import more_itertools, sys; print(sys.version_info[:2])"
        )
        assert rc == 0
        assert b"(3, 6)" in stdout


def test_setup_python_multiple_transitive_markers():
    # type: () -> None
    py27_interpreter = ensure_python_interpreter(PY27)
    py36_interpreter = ensure_python_interpreter(PY36)
    with temporary_dir() as out:
        pex = os.path.join(out, "pex.pex")
        results = run_pex_command(
            [
                "jsonschema==2.6.0",
                "--disable-cache",
                "--python-shebang=#!/usr/bin/env python",
                "--python={}".format(py27_interpreter),
                "--python={}".format(py36_interpreter),
                "-o",
                pex,
            ]
        )
        results.assert_success()

        pex_program = [pex, "-c"]
        py2_only_program = pex_program + ["import functools32"]
        both_program = pex_program + [
            "import jsonschema, os, sys; print(os.path.realpath(sys.executable))"
        ]

        py27_env = make_env(PATH=os.path.dirname(py27_interpreter))
        subprocess.check_call(py2_only_program, env=py27_env)

        stdout = subprocess.check_output(both_program, env=py27_env)
        assert to_bytes(os.path.realpath(py27_interpreter)) == stdout.strip()

        py36_env = make_env(PATH=os.path.dirname(py36_interpreter))
        with pytest.raises(subprocess.CalledProcessError) as err:
            subprocess.check_output(py2_only_program, stderr=subprocess.STDOUT, env=py36_env)
        assert b"ModuleNotFoundError: No module named 'functools32'" in err.value.output

        stdout = subprocess.check_output(both_program, env=py36_env)
        assert to_bytes(os.path.realpath(py36_interpreter)) == stdout.strip()


def test_setup_python_direct_markers():
    # type: () -> None
    py36_interpreter = ensure_python_interpreter(PY36)
    with temporary_dir() as out:
        pex = os.path.join(out, "pex.pex")
        results = run_pex_command(
            [
                'subprocess32==3.2.7; python_version<"3"',
                "--disable-cache",
                "--python-shebang=#!/usr/bin/env python",
                "--python={}".format(py36_interpreter),
                "-o",
                pex,
            ]
        )
        results.assert_success()

        py2_only_program = [pex, "-c", "import subprocess32"]

        with pytest.raises(subprocess.CalledProcessError) as err:
            subprocess.check_output(
                py2_only_program,
                stderr=subprocess.STDOUT,
                env=make_env(PATH=os.path.dirname(py36_interpreter)),
            )
        assert b"ModuleNotFoundError: No module named 'subprocess32'" in err.value.output


def test_setup_python_multiple_direct_markers():
    # type: () -> None
    py36_interpreter = ensure_python_interpreter(PY36)
    py27_interpreter = ensure_python_interpreter(PY27)
    with temporary_dir() as out:
        pex = os.path.join(out, "pex.pex")
        results = run_pex_command(
            [
                'subprocess32==3.2.7; python_version<"3"',
                "--disable-cache",
                "--python-shebang=#!/usr/bin/env python",
                "--python={}".format(py36_interpreter),
                "--python={}".format(py27_interpreter),
                "-o",
                pex,
            ]
        )
        results.assert_success()

        py2_only_program = [pex, "-c", "import subprocess32"]

        with pytest.raises(subprocess.CalledProcessError) as err:
            subprocess.check_output(
                py2_only_program,
                stderr=subprocess.STDOUT,
                env=make_env(PATH=os.path.dirname(py36_interpreter)),
            )
        assert (
            re.search(b"ModuleNotFoundError: No module named 'subprocess32'", err.value.output)
            is not None
        )

        subprocess.check_call(
            py2_only_program, env=make_env(PATH=os.path.dirname(py27_interpreter))
        )


def test_force_local_implicit_ns_packages_issues_598():
    # type: () -> None
    # This was a minimal repro for the issue documented in #598.
    with temporary_dir() as out:
        tcl_pex = os.path.join(out, "tcl.pex")
        run_pex_command(["twitter.common.lang==0.3.9", "-o", tcl_pex])

        subprocess.check_call(
            [tcl_pex, "-c", "from twitter.common.lang import Singleton"],
            env=make_env(PEX_FORCE_LOCAL="1", PEX_PATH=tcl_pex),
        )


@pytest.mark.skipif(
    IS_PYPY,
    reason="On PyPy this causes this error: Failed to execute PEX file. Needed "
    "manylinux2014_x86_64-pp-272-pypy_41 compatible dependencies for 1: "
    "cryptography==2.5 But this pex only contains "
    "cryptography-2.5-pp27-pypy_41-linux_x86_64.whl. "
    "Temporarily skipping the test on PyPy allows us to get tests passing "
    "again, until we can address this.",
)
def test_issues_661_devendoring_required():
    # type: () -> None
    # The cryptography distribution does not have a whl released for python3 on linux at version 2.5.
    # As a result, we're forced to build it under python3 and, prior to the fix for
    # https://github.com/pantsbuild/pex/issues/661, this would fail using the vendored setuptools
    # inside pex.
    with temporary_dir() as td:
        cryptography_pex = os.path.join(td, "cryptography.pex")
        res = run_pex_command(["cryptography==2.5", "-o", cryptography_pex])
        res.assert_success()

        subprocess.check_call([cryptography_pex, "-c", "import cryptography"])


def build_and_execute_pex_with_warnings(*extra_build_args, **extra_runtime_env):
    # type: (*str, **str) -> bytes
    with temporary_dir() as out:
        tcl_pex = os.path.join(out, "tcl.pex")
        run_pex_command(["twitter.common.lang==0.3.10", "-o", tcl_pex] + list(extra_build_args))

        cmd = [tcl_pex, "-c", "from twitter.common.lang import Singleton"]
        env = os.environ.copy()
        env.update(**extra_runtime_env)
        process = subprocess.Popen(cmd, env=env, stderr=subprocess.PIPE)
        _, stderr = process.communicate()
        return stderr


def test_emit_warnings_default():
    # type: () -> None
    stderr = build_and_execute_pex_with_warnings()
    assert stderr


def test_no_emit_warnings():
    # type: () -> None
    stderr = build_and_execute_pex_with_warnings("--no-emit-warnings")
    assert not stderr


def test_no_emit_warnings_emit_env_override():
    # type: () -> None
    stderr = build_and_execute_pex_with_warnings("--no-emit-warnings", PEX_EMIT_WARNINGS="true")
    assert stderr


def test_no_emit_warnings_verbose_override():
    # type: () -> None
    stderr = build_and_execute_pex_with_warnings("--no-emit-warnings", PEX_VERBOSE="1")
    assert stderr


def test_undeclared_setuptools_import_on_pex_path():
    # type: () -> None
    """Test that packages which access pkg_resources at import time can be found with pkg_resources.

    See https://github.com/pantsbuild/pex/issues/729 for context. We warn when a package accesses
    pkg_resources without declaring it in install_requires, but we also want to check that those
    packages can be accessed successfully via the PEX_PATH.
    """
    with temporary_dir() as td:
        setuptools_pex = os.path.join(td, "setuptools.pex")
        # NB: the specific setuptools version does not necessarily matter. We only pin the version to
        # avoid a future version of setuptools potentially fixing this issue and then us no longer
        # checking that Pex is behaving properly for older setuptools versions.
        run_pex_command(["setuptools==40.6.3", "-o", setuptools_pex]).assert_success()
        bigquery_pex = os.path.join(td, "bigquery.pex")
        run_pex_command(["google-cloud-bigquery==1.10.0", "-o", bigquery_pex]).assert_success()

        src_dir = os.path.join(td, "src")
        os.mkdir(src_dir)

        src_file = os.path.join(src_dir, "execute_import.py")
        with open(src_file, "w") as fp:
            fp.write(
                dedent(
                    """\
                    from google.cloud import bigquery

                    print('bigquery version: {}'.format(bigquery.__version__))
        """
                )
            )

        res = run_pex_command(
            [
                "--pex-path={}".format(":".join([setuptools_pex, bigquery_pex])),
                "-D",
                src_dir,
                "--entry-point",
                "execute_import",
            ]
        )
        res.assert_success()
        assert res.output.strip() == "bigquery version: 1.10.0"


def test_pkg_resource_early_import_on_pex_path():
    # type: () -> None
    """Test that packages which access pkg_resources at import time can be found with pkg_resources.

    See https://github.com/pantsbuild/pex/issues/749 for context. We only declare namespace packages
    once all environments have been resolved including ones passed in via PEX_PATH. This avoids
    importing pkg_resources too early which is potentially impactful with packages interacting with
    pkg_resources at import time.
    """
    with temporary_dir() as td:

        six_pex = os.path.join(td, "six.pex")
        run_pex_command(["six", "-o", six_pex]).assert_success()

        src_dir = os.path.join(td, "src")
        os.mkdir(src_dir)

        src_file = os.path.join(src_dir, "execute_import.py")
        with open(src_file, "w") as fp:
            fp.write(
                dedent(
                    """\
                    import pkg_resources
                    import sys

                    pkg_resources.get_distribution('six')
                    """
                )
            )

        setuptools_pex = os.path.join(td, "autopep8.pex")
        run_pex_command(
            [
                "autopep8",
                "setuptools",
                "-D",
                src_dir,
                "--entry-point",
                "execute_import",
                "-o",
                setuptools_pex,
            ]
        ).assert_success()
        _, return_code = run_simple_pex(setuptools_pex, env=make_env(PEX_PATH=six_pex))
        assert return_code == 0


@pytest.mark.skipif(
    IS_PYPY,
    reason="The cryptography 2.6.1 project only has pre-built wheels for CPython "
    "available on PyPI and this test relies upon a pre-built wheel being "
    "available.",
)
def test_issues_539_abi3_resolution():
    # type: () -> None
    # The cryptography team releases the following relevant pre-built wheels for version 2.6.1:
    # cryptography-2.6.1-cp27-cp27m-macosx_10_6_intel.whl
    # cryptography-2.6.1-cp27-cp27m-manylinux1_x86_64.whl
    # cryptography-2.6.1-cp27-cp27mu-manylinux1_x86_64.whl
    # cryptography-2.6.1-cp34-abi3-macosx_10_6_intel.whl
    # cryptography-2.6.1-cp34-abi3-manylinux1_x86_64.whl
    # With pex in --no-build mode, we force a test that pex abi3 resolution works when this test is
    # run under CPython>3.4,<4 on OSX and linux.

    with temporary_dir() as td:
        # The dependency graph for cryptography-2.6.1 includes pycparser which is only released as an
        # sdist. Since we want to test in --no-build, we pre-resolve/build the pycparser wheel here and
        # add the resulting wheelhouse to the --no-build pex command.
        download_dir = os.path.join(td, ".downloads")
        get_pip().spawn_download_distributions(
            download_dir=download_dir, requirements=["pycparser"]
        ).wait()
        wheel_dir = os.path.join(td, ".wheels")
        get_pip().spawn_build_wheels(
            wheel_dir=wheel_dir, distributions=glob.glob(os.path.join(download_dir, "*"))
        ).wait()

        cryptography_pex = os.path.join(td, "cryptography.pex")
        res = run_pex_command(
            ["-f", wheel_dir, "--no-build", "cryptography==2.6.1", "-o", cryptography_pex]
        )
        res.assert_success()

        subprocess.check_call([cryptography_pex, "-c", "import cryptography"])


def assert_reproducible_build(args):
    # type: (List[str]) -> None
    with temporary_dir() as td:
        pex1 = os.path.join(td, "1.pex")
        pex2 = os.path.join(td, "2.pex")

        # Note that we change the `PYTHONHASHSEED` to ensure that there are no issues resulting
        # from the random seed, such as data structures, as Tox sets this value by default. See
        # https://tox.readthedocs.io/en/latest/example/basic.html#special-handling-of-pythonhashseed.
        def create_pex(path, seed):
            result = run_pex_command(args + ["-o", path], env=make_env(PYTHONHASHSEED=seed))
            result.assert_success()

        create_pex(pex1, seed=111)
        # We sleep to ensure that there is no non-reproducibility from timestamps or
        # anything that may depend on the system time. Note that we must sleep for at least
        # 2 seconds, because the zip format uses 2 second precision per section 4.4.6 of
        # https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT.
        safe_sleep(2)
        create_pex(pex2, seed=22222)
        # First explode the PEXes to compare file-by-file for easier debugging.
        with ZipFile(pex1) as zf1, ZipFile(pex2) as zf2:
            unzipped1 = os.path.join(td, "pex1")
            unzipped2 = os.path.join(td, "pex2")
            zf1.extractall(path=unzipped1)
            zf2.extractall(path=unzipped2)
            for member1, member2 in zip(sorted(zf1.namelist()), sorted(zf2.namelist())):
                member1_path = os.path.join(unzipped1, member1)
                if os.path.isdir(member1_path):
                    continue
                member2_path = os.path.join(unzipped2, member2)
                assert filecmp.cmp(member1_path, member2_path, shallow=False)
        # Then compare the original .pex files. This is the assertion we truly care about.
        assert filecmp.cmp(pex1, pex2, shallow=False)


def test_reproducible_build_no_args():
    # type: () -> None
    assert_reproducible_build([])


def test_reproducible_build_bdist_requirements():
    # type: () -> None
    # We test both a pure Python wheel (six) and a platform-specific wheel (cryptography).
    assert_reproducible_build(["six==1.12.0", "cryptography==2.6.1"])


def test_reproducible_build_sdist_requirements():
    # type: () -> None
    assert_reproducible_build(["pycparser==2.19", "--no-wheel"])


def test_reproducible_build_m_flag():
    # type: () -> None
    assert_reproducible_build(["-m", "pydoc"])


def test_reproducible_build_c_flag_from_source():
    # type: () -> None
    setup_py = dedent(
        """\
        from setuptools import setup

        setup(
            name='my_app',
            entry_points={'console_scripts': ['my_app_function = my_app:do_something']},
        )
  """
    )
    my_app = dedent(
        """\
        def do_something():
            return "reproducible"
        """
    )
    with temporary_content({"setup.py": setup_py, "my_app.py": my_app}) as project_dir:
        assert_reproducible_build([project_dir, "-c", "my_app_function"])


def test_reproducible_build_c_flag_from_dependency():
    # type: () -> None
    assert_reproducible_build(["future==0.17.1", "-c", "futurize"])


def test_reproducible_build_python_flag():
    # type: () -> None
    assert_reproducible_build(["--python=python2.7"])


def test_reproducible_build_python_shebang_flag():
    # type: () -> None
    assert_reproducible_build(["--python-shebang=/usr/bin/python"])


def test_issues_736_requirement_setup_py_with_extras():
    # type: () -> None
    with make_source_dir(
        name="project1", version="1.0.0", extras_require={"foo": ["project2"]}
    ) as project1_dir:
        with built_wheel(name="project2", version="2.0.0") as project2_bdist:
            with temporary_dir() as td:
                safe_copy(project2_bdist, os.path.join(td, os.path.basename(project2_bdist)))

                project1_pex = os.path.join(td, "project1.pex")
                result = run_pex_command(
                    ["-f", td, "-o", project1_pex, "{}[foo]".format(project1_dir)]
                )
                result.assert_success()

                output = subprocess.check_output(
                    [
                        project1_pex,
                        "-c",
                        "from project2 import my_module; my_module.do_something()",
                    ],
                    env=make_env(PEX_INTERPRETER="1"),
                )
                assert output.decode("utf-8").strip() == u"hello world!"


def _assert_exec_chain(
    exec_chain=None,  # type: Optional[List[str]]
    pex_python=None,  # type: Optional[str]
    pex_python_path=None,  # type: Optional[Iterable[str]]
    interpreter_constraints=None,  # type: Optional[Iterable[str]]
    pythonpath=None,  # type: Optional[Iterable[str]]
):
    # type: (...) -> None
    with temporary_dir() as td:
        test_pex = os.path.join(td, "test.pex")

        args = ["-o", test_pex]
        if interpreter_constraints:
            args.extend("--interpreter-constraint={}".format(ic) for ic in interpreter_constraints)

        env = os.environ.copy()
        PATH = env["PATH"].split(os.pathsep)

        def add_to_path(entry):
            # type: (str) -> None
            if os.path.isfile(entry):
                entry = os.path.dirname(entry)
            PATH.append(entry)

        if pex_python:
            add_to_path(pex_python)
        if pex_python_path:
            for path in pex_python_path:
                add_to_path(path)

        env["PATH"] = os.pathsep.join(PATH)
        result = run_pex_command(args, env=env)
        result.assert_success()

        env = make_env(
            _PEX_EXEC_CHAIN=1,
            PEX_INTERPRETER=1,
            PEX_PYTHON=pex_python,
            PEX_PYTHON_PATH=os.pathsep.join(pex_python_path) if pex_python_path else None,
            PYTHONPATH=os.pathsep.join(pythonpath) if pythonpath else None,
        )

        initial_interpreter = PythonInterpreter.get()
        output = subprocess.check_output(
            [
                initial_interpreter.binary,
                test_pex,
                "-c",
                "import json, os; print(json.dumps(os.environ.copy()))",
            ],
            env=env,
        )
        final_env = json.loads(output.decode("utf-8"))

        assert "PEX_PYTHON" not in final_env
        assert "PEX_PYTHON_PATH" not in final_env
        assert "_PEX_SHOULD_EXIT_BOOTSTRAP_REEXEC" not in final_env

        expected_exec_interpreters = [initial_interpreter]
        if exec_chain:
            expected_exec_interpreters.extend(PythonInterpreter.from_binary(b) for b in exec_chain)
        final_interpreter = expected_exec_interpreters[-1]
        if final_interpreter.is_venv:
            # If the last interpreter in the chain is in a virtual environment, it should be fully
            # resolved and re-exec'd against in order to escape the virtual environment since we're
            # not setting PEX_INHERIT_PATH in these tests.
            resolved = final_interpreter.resolve_base_interpreter()
            if exec_chain:
                # There is already an expected reason to re-exec; so no extra exec step is needed.
                expected_exec_interpreters[-1] = resolved
            else:
                # The expected exec chain is just the initial_interpreter, but it turned out to be a
                # venv which forces a re-exec.
                expected_exec_interpreters.append(resolved)
        expected_exec_chain = [i.binary for i in expected_exec_interpreters]
        actual_exec_chain = final_env["_PEX_EXEC_CHAIN"].split(os.pathsep)
        assert expected_exec_chain == actual_exec_chain


def test_pex_no_reexec_no_constraints():
    # type: () -> None
    _assert_exec_chain()


def test_pex_reexec_no_constraints_pythonpath_present():
    # type: () -> None
    _assert_exec_chain(exec_chain=[sys.executable], pythonpath=["."])


def test_pex_no_reexec_constraints_match_current():
    # type: () -> None
    _assert_exec_chain(interpreter_constraints=[PythonInterpreter.get().identity.requirement])


def test_pex_reexec_constraints_match_current_pythonpath_present():
    # type: () -> None
    _assert_exec_chain(
        exec_chain=[sys.executable],
        pythonpath=["."],
        interpreter_constraints=[PythonInterpreter.get().identity.requirement],
    )


def test_pex_reexec_constraints_dont_match_current_pex_python_path():
    # type: () -> None
    py36_interpreter = ensure_python_interpreter(PY36)
    py27_interpreter = ensure_python_interpreter(PY27)
    _assert_exec_chain(
        exec_chain=[py36_interpreter],
        pex_python_path=[py27_interpreter, py36_interpreter],
        interpreter_constraints=["=={}".format(PY36)],
    )


def test_pex_reexec_constraints_dont_match_current_pex_python_path_min_py_version_selected():
    # type: () -> None
    py36_interpreter = ensure_python_interpreter(PY36)
    py27_interpreter = ensure_python_interpreter(PY27)
    _assert_exec_chain(
        exec_chain=[py27_interpreter], pex_python_path=[py36_interpreter, py27_interpreter]
    )


def test_pex_reexec_constraints_dont_match_current_pex_python():
    # type: () -> None
    version = PY27 if sys.version_info[0:2] == (3, 6) else PY36
    interpreter = ensure_python_interpreter(version)
    _assert_exec_chain(
        exec_chain=[interpreter],
        pex_python=interpreter,
        interpreter_constraints=["=={}".format(version)],
    )


def test_issues_745_extras_isolation():
    # type: () -> None
    # Here we ensure one of our extras, `subprocess32`, is properly isolated in the transition from
    # pex bootstrapping where it is imported by `pex.executor` to execution of user code.
    python, pip = ensure_python_venv(PY27)
    subprocess.check_call([pip, "install", "subprocess32"])
    with temporary_dir() as td:
        src_dir = os.path.join(td, "src")
        with safe_open(os.path.join(src_dir, "test_issues_745.py"), "w") as fp:
            fp.write(
                dedent(
                    """\
                    import subprocess32

                    print(subprocess32.__file__)
                    """
                )
            )

        pex_file = os.path.join(td, "test.pex")

        run_pex_command(
            [
                "--sources-directory={}".format(src_dir),
                "--entry-point=test_issues_745",
                "-o",
                pex_file,
            ],
            python=python,
        )

        # The pex runtime should scrub subprocess32 since it comes from site-packages and so we should
        # not have access to it.
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_call([python, pex_file])

        # But if the pex has a declared dependency on subprocess32 we should be able to find the
        # subprocess32 bundled into the pex.
        pex_root = os.path.realpath(os.path.join(td, "pex_root"))
        run_pex_command(
            [
                "subprocess32",
                "--sources-directory={}".format(src_dir),
                "--entry-point=test_issues_745",
                "-o",
                pex_file,
            ],
            python=python,
        )

        output = subprocess.check_output([python, pex_file], env=make_env(PEX_ROOT=pex_root))

        subprocess32_location = os.path.realpath(output.decode("utf-8").strip())
        assert subprocess32_location.startswith(pex_root)


@pytest.fixture
def issues_1025_pth():
    def safe_rm(path):
        try:
            os.unlink(path)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    cleanups = []

    def write_pth(pth_path, sitedir):
        cleanups.append(lambda: safe_rm(pth_path))
        with open(pth_path, "w") as fp:
            fp.write("import site; site.addsitedir({!r})\n".format(sitedir))

    try:
        yield write_pth
    finally:
        for cleanup in cleanups:
            cleanup()


def test_issues_1025_extras_isolation(issues_1025_pth):
    python, pip = ensure_python_venv(PY36)
    interpreter = PythonInterpreter.from_binary(python)
    _, stdout, _ = interpreter.execute(args=["-c", "import site; print(site.getsitepackages()[0])"])
    with temporary_dir() as tmpdir:
        sitedir = os.path.join(tmpdir, "sitedir")
        Executor.execute(cmd=[pip, "install", "--target", sitedir, "ansicolors==1.1.8"])

        pth_path = os.path.join(stdout.strip(), "issues_1025.{}.pth".format(uuid.uuid4().hex))
        issues_1025_pth(pth_path, sitedir)

        pex_file = os.path.join(tmpdir, "isolated.pex")
        results = run_pex_command(args=["-o", pex_file], python=python)
        results.assert_success()

        output, returncode = run_simple_pex(
            pex_file,
            args=["-c", "import colors"],
            interpreter=interpreter,
            env=make_env(PEX_VERBOSE="9"),
        )
        assert returncode != 0, output

        output, returncode = run_simple_pex(
            pex_file,
            args=["-c", "import colors"],
            interpreter=interpreter,
            env=make_env(PEX_VERBOSE="9", PEX_INHERIT_PATH="fallback"),
        )
        assert returncode == 0, output


def test_trusted_host_handling():
    # type: () -> None
    python = ensure_python_interpreter(PY27)
    # Since we explicitly ask Pex to find links at http://www.antlr3.org/download/Python, it should
    # implicitly trust the www.antlr3.org host.
    results = run_pex_command(
        args=[
            "--find-links=http://www.antlr3.org/download/Python",
            "antlr_python_runtime==3.1.3",
            "--",
            "-c",
            "import antlr3",
        ],
        python=python,
    )
    results.assert_success()


def test_issues_898():
    # type: () -> None
    python27 = ensure_python_interpreter(PY27)
    python36 = ensure_python_interpreter(PY36)
    with temporary_dir() as td:
        src_dir = os.path.join(td, "src")
        with safe_open(os.path.join(src_dir, "test_issues_898.py"), "w") as fp:
            fp.write(
                dedent(
                    """
                    import zipp

                    print(zipp.__file__)
                    """
                )
            )

        pex_file = os.path.join(td, "zipp.pex")

        results = run_pex_command(
            args=[
                "--python={}".format(python27),
                "--python={}".format(python36),
                "zipp>=1,<=3.1.0",
                "--sources-directory={}".format(src_dir),
                "--entry-point=test_issues_898",
                "-o",
                pex_file,
            ],
        )
        results.assert_success()

        pex_root = os.path.realpath(os.path.join(td, "pex_root"))
        for python in python27, python36:
            output = subprocess.check_output([python, pex_file], env=make_env(PEX_ROOT=pex_root))
            zipp_location = os.path.realpath(output.decode("utf-8").strip())
            assert zipp_location.startswith(
                pex_root
            ), "Failed to import zipp from {} under {}".format(pex_file, python)


def test_pex_run_strip_env():
    # type: () -> None
    with temporary_dir() as td:
        src_dir = os.path.join(td, "src")
        with safe_open(os.path.join(src_dir, "print_pex_env.py"), "w") as fp:
            fp.write(
                dedent(
                    """
                    import json
                    import os

                    print(json.dumps({k: v for k, v in os.environ.items() if k.startswith('PEX_')}))
                    """
                )
            )

        pex_env = dict(PEX_ROOT=os.path.join(td, "pex_root"))
        env = make_env(**pex_env)

        stripped_pex_file = os.path.join(td, "stripped.pex")
        results = run_pex_command(
            args=[
                "--sources-directory={}".format(src_dir),
                "--entry-point=print_pex_env",
                "-o",
                stripped_pex_file,
            ],
        )
        results.assert_success()
        assert {} == json.loads(
            subprocess.check_output([stripped_pex_file], env=env).decode("utf-8")
        ), "Expected the entrypoint environment to be stripped of PEX_ environment variables."

        unstripped_pex_file = os.path.join(td, "unstripped.pex")
        results = run_pex_command(
            args=[
                "--sources-directory={}".format(src_dir),
                "--entry-point=print_pex_env",
                "--no-strip-pex-env",
                "-o",
                unstripped_pex_file,
            ],
        )
        results.assert_success()
        assert pex_env == json.loads(
            subprocess.check_output([unstripped_pex_file], env=env).decode("utf-8")
        ), "Expected the entrypoint environment to be left un-stripped."


def iter_distributions(pex_root, project_name):
    # type: (str, str) -> Iterator[pkg_resources.Distribution]
    found = set()
    for root, dirs, _ in os.walk(pex_root):
        for d in dirs:
            if not d.startswith(project_name):
                continue
            if not d.endswith(".whl"):
                continue
            wheel_path = os.path.realpath(os.path.join(root, d))
            if wheel_path in found:
                continue
            dist = DistributionHelper.distribution_from_path(wheel_path)
            assert dist is not None
            if dist.project_name == project_name:
                found.add(wheel_path)
                yield dist


def test_pex_cache_dir_and_pex_root():
    # type: () -> None
    python = ensure_python_interpreter(PY36)
    with temporary_dir() as td:
        cache_dir = os.path.join(td, "cache_dir")
        pex_root = os.path.join(td, "pex_root")

        # When the options both have the same value it should be accepted.
        pex_file = os.path.join(td, "pex_file")
        run_pex_command(
            python=python,
            args=["--cache-dir", cache_dir, "--pex-root", cache_dir, "p537==1.0.3", "-o", pex_file],
        ).assert_success()

        dists = list(iter_distributions(pex_root=cache_dir, project_name="p537"))
        assert 1 == len(dists), "Expected to find exactly one distribution, found {}".format(dists)

        for directory in cache_dir, pex_root:
            safe_rmtree(directory)

        # When the options have conflicting values they should be rejected.
        run_pex_command(
            python=python,
            args=["--cache-dir", cache_dir, "--pex-root", pex_root, "p537==1.0.3", "-o", pex_file],
        ).assert_failure()

        assert not os.path.exists(cache_dir)
        assert not os.path.exists(pex_root)


def test_disable_cache():
    # type: () -> None
    python = ensure_python_interpreter(PY36)
    with temporary_dir() as td:
        pex_root = os.path.join(td, "pex_root")
        pex_file = os.path.join(td, "pex_file")
        run_pex_command(
            python=python,
            args=["--disable-cache", "p537==1.0.3", "-o", pex_file],
            env=make_env(PEX_ROOT=pex_root),
        ).assert_success()

        assert not os.path.exists(pex_root)


def test_unzip_mode():
    # type: () -> None
    with temporary_dir() as td:
        pex_root = os.path.join(td, "pex_root")
        pex_file = os.path.join(td, "pex_file")
        src_dir = os.path.join(td, "src")
        with safe_open(os.path.join(src_dir, "example.py"), "w") as fp:
            fp.write(
                dedent(
                    """
                    import os
                    import sys

                    if 'quit' == sys.argv[-1]:
                        print(os.path.realpath(sys.argv[0]))
                        sys.exit(0)

                    print(' '.join(sys.argv[1:]))
                    sys.stdout.flush()
                    os.execv(sys.argv[0], sys.argv[:-1])
                    """
                )
            )
        run_pex_command(
            args=[
                "--sources-directory",
                src_dir,
                "--entry-point",
                "example",
                "--output-file",
                pex_file,
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--no-strip-pex-env",
                "--unzip",
            ]
        ).assert_success()

        output1 = subprocess.check_output(
            args=[pex_file, "quit", "re-exec"],
        )
        assert ["quit re-exec", os.path.realpath(pex_file)] == output1.decode("utf-8").splitlines()

        pex_hash = PexInfo.from_pex(pex_file).pex_hash
        assert pex_hash is not None
        unzipped_cache = unzip_dir(pex_root, pex_hash)
        assert os.path.isdir(unzipped_cache)
        shutil.rmtree(unzipped_cache)

        output2 = subprocess.check_output(
            args=[pex_file, "quit", "re-exec"], env=make_env(PEX_UNZIP=False)
        )
        assert output1 == output2
        assert not os.path.exists(unzipped_cache)


def test_issues_996():
    # type: () -> None
    python27 = ensure_python_interpreter(PY27)
    python36 = ensure_python_interpreter(PY36)
    pex_python_path = os.pathsep.join((python27, python36))

    def create_platform_pex(args):
        # type: (List[str]) -> IntegResults
        return run_pex_command(
            args=["--platform", str(PythonInterpreter.from_binary(python36).platform)] + args,
            python=python27,
            env=make_env(PEX_PYTHON_PATH=pex_python_path),
        )

    with temporary_dir() as td:
        pex_file = os.path.join(td, "pex_file")

        # N.B.: We use psutil since only an sdist is available for linux and osx and the distribution
        # has no dependencies.
        args = ["psutil==5.7.0", "-o", pex_file]

        # By default, no --platforms are resolved and so distributions must be available in binary form.
        results = create_platform_pex(args)
        results.assert_failure()

        # If --platform resolution is enabled however, we should be able to find a corresponding local
        # interpreter to perform a full-featured resolve with.
        results = create_platform_pex(["--resolve-local-platforms"] + args)
        results.assert_success()

        output, returncode = run_simple_pex(
            pex=pex_file,
            args=("-c", "import psutil; print(psutil.cpu_count())"),
            interpreter=PythonInterpreter.from_binary(python36),
        )
        assert 0 == returncode
        assert int(output.strip()) >= multiprocessing.cpu_count()


@pytest.fixture
def tmp_workdir():
    # type: () -> Iterator[str]
    cwd = os.getcwd()
    with temporary_dir() as tmpdir:
        os.chdir(tmpdir)
        try:
            yield os.path.realpath(tmpdir)
        finally:
            os.chdir(cwd)


def test_tmpdir_absolute(tmp_workdir):
    # type: (str) -> None
    result = run_pex_command(
        args=[
            "--tmpdir",
            ".",
            "--",
            "-c",
            dedent(
                """\
                import os
                import tempfile
                
                print(os.environ["TMPDIR"])
                print(tempfile.gettempdir())
                """
            ),
        ]
    )
    result.assert_success()
    assert [tmp_workdir, tmp_workdir] == result.output.strip().splitlines()


def test_tmpdir_dne(tmp_workdir):
    # type: (str) -> None
    tmpdir_dne = os.path.join(tmp_workdir, ".tmp")
    result = run_pex_command(args=["--tmpdir", ".tmp", "--", "-c", ""])
    result.assert_failure()
    assert tmpdir_dne in result.error
    assert "does not exist" in result.error


def test_tmpdir_file(tmp_workdir):
    # type: (str) -> None
    tmpdir_file = os.path.join(tmp_workdir, ".tmp")
    touch(tmpdir_file)
    result = run_pex_command(args=["--tmpdir", ".tmp", "--", "-c", ""])
    result.assert_failure()
    assert tmpdir_file in result.error
    assert "is not a directory" in result.error


def test_resolve_arbitrary_equality_issues_940():
    # type: () -> None
    with temporary_dir() as tmpdir, built_wheel(
        name="foo",
        version="1.0.2-fba4511",
        python_requires=">=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*",
    ) as whl:
        pex_file = os.path.join(tmpdir, "pex")
        results = run_pex_command(args=["-o", pex_file, whl])
        results.assert_success()

        stdout, returncode = run_simple_pex(pex_file, args=["-c", "import foo"])
        assert returncode == 0
        assert stdout == b""


def test_resolve_python_requires_full_version_issues_1017():
    # type: () -> None
    python36 = ensure_python_interpreter(PY36)
    result = run_pex_command(
        python=python36,
        args=[
            "pandas==1.0.5",
            "--",
            "-c",
            "import pandas; print(pandas._version.get_versions()['version'])",
        ],
        quiet=True,
    )
    result.assert_success()
    assert "1.0.5" == result.output.strip()


@pytest.fixture(scope="module")
def mitmdump():
    # type: () -> Tuple[str, str]
    python, pip = ensure_python_venv(PY36)
    subprocess.check_call([pip, "install", "mitmproxy==5.3.0"])
    mitmdump = os.path.join(os.path.dirname(python), "mitmdump")
    return mitmdump, os.path.expanduser("~/.mitmproxy/mitmproxy-ca-cert.pem")


@pytest.fixture
def run_proxy(mitmdump, tmp_workdir):
    # type: (Tuple[str, str], str) -> Callable[[Optional[str]], ContextManager[Tuple[int, str]]]
    messages = os.path.join(tmp_workdir, "messages")
    addon = os.path.join(tmp_workdir, "addon.py")
    with open(addon, "w") as fp:
        fp.write(
            dedent(
                """\
                from mitmproxy import ctx
        
                class NotifyUp:
                    def running(self) -> None:
                        port = ctx.master.server.address[1]
                        with open({msg_channel!r}, "w") as fp:
                            print(str(port), file=fp)
        
                addons = [NotifyUp()]
                """.format(
                    msg_channel=messages
                )
            )
        )

    @contextmanager
    def _run_proxy(
        proxy_auth=None,  # type: Optional[str]
    ):
        # type: (...) -> Iterator[Tuple[int, str]]
        os.mkfifo(messages)
        proxy, ca_cert = mitmdump
        args = [proxy, "-p", "0", "-s", addon]
        if proxy_auth:
            args.extend(["--proxyauth", proxy_auth])
        proxy_process = subprocess.Popen(args)
        try:
            with open(messages, "r") as fp:
                port = int(fp.readline().strip())
                yield port, ca_cert
        finally:
            proxy_process.kill()
            os.unlink(messages)

    return _run_proxy


EXAMPLE_PYTHON_REQUIREMENTS_URL = (
    "https://raw.githubusercontent.com/pantsbuild/example-python/"
    "c6052498f25a436f2639ccd0bc846cec1a55d7d5"
    "/requirements.txt"
)


def test_requirements_network_configuration(run_proxy, tmp_workdir):
    # type: (Callable[[Optional[str]], ContextManager[Tuple[int, str]]], str) -> None
    def req(
        contents,  # type: str
        line_no,  # type: int
    ):
        return PyPIRequirement.create(
            LogicalLine(
                "{}\n".format(contents),
                contents,
                source=EXAMPLE_PYTHON_REQUIREMENTS_URL,
                start_line=line_no,
                end_line=line_no,
            ),
            Requirement.parse(contents),
        )

    proxy_auth = "jake:jones"
    with run_proxy(proxy_auth) as (port, ca_cert):
        reqs = parse_requirement_file(
            EXAMPLE_PYTHON_REQUIREMENTS_URL,
            fetcher=URLFetcher(
                NetworkConfiguration.create(
                    proxy="{proxy_auth}@localhost:{port}".format(proxy_auth=proxy_auth, port=port),
                    cert=ca_cert,
                )
            ),
        )
        assert [
            req("ansicolors>=1.0.2", 4),
            req("setuptools>=42.0.0", 5),
            req("translate>=3.2.1", 6),
            req("protobuf>=3.11.3", 7),
        ] == list(reqs)


@pytest.mark.parametrize(
    "py_version",
    [
        pytest.param(PY27, id="virtualenv-16.7.10"),
        pytest.param(PY36, id="pyvenv"),
    ],
)
def test_issues_1031(py_version):
    # type: (str) -> None
    system_site_packages_venv, _ = ensure_python_venv(
        py_version, latest_pip=False, system_site_packages=True
    )
    standard_venv, _ = ensure_python_venv(py_version, latest_pip=False, system_site_packages=False)

    print_sys_path_code = "import os, sys; print('\\n'.join(map(os.path.realpath, sys.path)))"

    def get_sys_path(python):
        # type: (str) -> MutableSet[str]
        _, stdout, _ = PythonInterpreter.from_binary(python).execute(
            args=["-c", print_sys_path_code]
        )
        return OrderedSet(stdout.strip().splitlines())

    system_site_packages_venv_sys_path = get_sys_path(system_site_packages_venv)
    standard_venv_sys_path = get_sys_path(standard_venv)

    def venv_dir(python):
        # type: (str) -> str
        bin_dir = os.path.dirname(python)
        venv_dir = os.path.dirname(bin_dir)
        return os.path.realpath(venv_dir)

    system_site_packages = {
        p
        for p in (system_site_packages_venv_sys_path - standard_venv_sys_path)
        if not p.startswith((venv_dir(system_site_packages_venv), venv_dir(standard_venv)))
    }
    assert len(system_site_packages) == 1, (
        "system_site_packages_venv_sys_path:\n"
        "\t{}\n"
        "standard_venv_sys_path:\n"
        "\t{}\n"
        "difference:\n"
        "\t{}".format(
            "\n\t".join(system_site_packages_venv_sys_path),
            "\n\t".join(standard_venv_sys_path),
            "\n\t".join(system_site_packages),
        )
    )
    system_site_packages_path = system_site_packages.pop()

    def get_system_site_packages_pex_sys_path(**env):
        # type: (**Any) -> MutableSet[str]
        output, returncode = run_simple_pex_test(
            body=print_sys_path_code,
            interpreter=PythonInterpreter.from_binary(system_site_packages_venv),
            env=make_env(**env),
        )
        assert returncode == 0
        return OrderedSet(output.decode("utf-8").strip().splitlines())

    assert system_site_packages_path not in get_system_site_packages_pex_sys_path()
    assert system_site_packages_path not in get_system_site_packages_pex_sys_path(
        PEX_INHERIT_PATH="false"
    )
    assert system_site_packages_path in get_system_site_packages_pex_sys_path(
        PEX_INHERIT_PATH="prefer"
    )
    assert system_site_packages_path in get_system_site_packages_pex_sys_path(
        PEX_INHERIT_PATH="fallback"
    )


@pytest.fixture
def isort_pex_args(tmpdir):
    # type: (Any) -> Tuple[str, List[str]]
    pex_file = os.path.join(str(tmpdir), "pex")

    requirements = [
        # For Python 2.7 and Python 3.5:
        "isort==4.3.21; python_version<'3.6'",
        "setuptools==44.1.1; python_version<'3.6'",
        # For Python 3.6+:
        "isort==5.6.4; python_version>='3.6'",
    ]
    return pex_file, requirements + ["-c", "isort", "-o", pex_file]


def test_venv_mode(
    tmpdir,  # type: Any
    isort_pex_args,  # type: Tuple[str, List[str]]
):
    # type: (...) -> None
    other_interpreter_version = PY36 if sys.version_info[0] == 2 else PY27
    other_interpreter = ensure_python_interpreter(other_interpreter_version)

    pex_file, args = isort_pex_args
    results = run_pex_command(
        args=args + ["--python", sys.executable, "--python", other_interpreter, "--venv"],
        quiet=True,
    )
    results.assert_success()

    def run_isort_pex(**env):
        # type: (**Any) -> str
        pex_root = str(tmpdir)
        stdout, returncode = run_simple_pex(
            pex_file,
            args=["-c", "import sys; print(sys.executable)"],
            env=make_env(PEX_ROOT=pex_root, PEX_INTERPRETER=1, **env),
        )
        assert returncode == 0, stdout
        pex_interpreter = cast(str, stdout.decode("utf-8").strip())
        with ENV.patch(**env):
            pex_info = PexInfo.from_pex(pex_file)
            pex_hash = pex_info.pex_hash
            assert pex_hash is not None
            expected_venv_home = venv_dir(pex_root, pex_hash, interpreter_constraints=[])
        assert expected_venv_home == os.path.commonprefix([pex_interpreter, expected_venv_home])
        return pex_interpreter

    isort_pex_interpreter1 = run_isort_pex()
    assert isort_pex_interpreter1 == run_isort_pex()

    isort_pex_interpreter2 = run_isort_pex(PEX_PYTHON=other_interpreter)
    assert other_interpreter != isort_pex_interpreter2
    assert isort_pex_interpreter1 != isort_pex_interpreter2
    assert isort_pex_interpreter2 == run_isort_pex(PEX_PYTHON=other_interpreter)


@pytest.mark.parametrize(
    "mode_args",
    [
        pytest.param([], id="PEX"),
        pytest.param(["--unzip"], id="unzip"),
        pytest.param(["--venv"], id="venv"),
    ],
)
def test_seed(
    isort_pex_args,  # type: Tuple[str, List[str]]
    mode_args,  # type: List[str]
):
    # type: (...) -> None
    pex_file, args = isort_pex_args
    results = run_pex_command(args=args + mode_args + ["--seed"], quiet=True)
    results.assert_success()

    seed_argv = shlex.split(results.output)
    isort_args = ["--version"]
    seed_stdout, seed_stderr = Executor.execute(seed_argv + isort_args)
    pex_stdout, pex_stderr = Executor.execute([pex_file] + isort_args)
    assert pex_stdout == seed_stdout
    assert pex_stderr == seed_stderr


def test_pip_issues_9420_workaround():
    # type: () -> None

    # N.B.: isort 5.7.0 needs Python >=3.6
    python = ensure_python_interpreter(PY36)

    results = run_pex_command(
        args=["--resolver-version", "pip-2020-resolver", "isort[colors]==5.7.0", "colorama==0.4.1"],
        python=python,
        quiet=True,
    )
    results.assert_failure()
    normalized_stderr = "\n".join(line.strip() for line in results.error.strip().splitlines())
    assert normalized_stderr.startswith(
        dedent(
            """\
            ERROR: Cannot install colorama==0.4.1 and isort[colors]==5.7.0 because these package versions have conflicting dependencies.
            ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/en/latest/user_guide/#fixing-conflicting-dependencies
            """
        )
    )
    assert normalized_stderr.endswith(
        dedent(
            """\
            The conflict is caused by:
            The user requested colorama==0.4.1
            isort[colors] 5.7.0 depends on colorama<0.5.0 and >=0.4.3; extra == "colors"

            To fix this you could try to:
            1. loosen the range of package versions you've specified
            2. remove package versions to allow pip attempt to solve the dependency conflict
            """
        ).strip()
    )


def test_requirement_file_from_url(tmpdir):
    # type: (Any) -> None
    pex_file = os.path.join(str(tmpdir), "pex")
    results = run_pex_command(args=["-r", EXAMPLE_PYTHON_REQUIREMENTS_URL, "-o", pex_file])
    results.assert_success()
    output, returncode = run_simple_pex(
        pex_file, args=["-c", "import colors, google.protobuf, setuptools, translate"]
    )
    assert 0 == returncode, output
    assert b"" == output


def test_constraint_file_from_url(tmpdir):
    # type: (Any) -> None

    # N.B.: The fasteners library requires Python >=3.6.
    python = ensure_python_interpreter(PY36)

    pex_file = os.path.join(str(tmpdir), "pex")

    # N.B.: This requirements file has fasteners==0.15.0 but fasteners 0.16.0 is available.
    # N.B.: This requirements file has 28 requirements in addition to fasteners.
    pants_requirements_url = (
        "https://raw.githubusercontent.com/pantsbuild/pants/"
        "b0fbb76112dcb61b3004c2caf3a59d3f03e3f182"
        "/3rdparty/python/requirements.txt"
    )
    results = run_pex_command(
        args=["fasteners", "--constraints", pants_requirements_url, "-o", pex_file], python=python
    )
    results.assert_success()
    output, returncode = run_simple_pex(
        pex_file,
        args=["-c", "from fasteners.version import version_string; print(version_string())"],
        interpreter=PythonInterpreter.from_binary(python),
    )
    assert 0 == returncode, output

    # Strange but true: https://github.com/harlowja/fasteners/blob/0.15/fasteners/version.py
    assert (
        b"0.14.1" == output.strip()
    ), "Fasteners 0.15.0 is expected to report its version as 0.14.1"

    # N.B.: Fasteners 0.15.0 depends on six and monotonic>=0.1; neither of which are constrained by
    # `pants_requirements_url`.
    dist_paths = set(PexInfo.from_pex(pex_file).distributions.keys())
    assert len(dist_paths) == 3
    dist_paths.remove("fasteners-0.15-py2.py3-none-any.whl")
    for dist_path in dist_paths:
        assert dist_path.startswith(("six-", "monotonic-")) and dist_path.endswith(".whl")


def test_top_level_environment_markers_issues_899(tmpdir):
    # type: (Any) -> None
    python27 = ensure_python_interpreter(PY27)
    python36 = ensure_python_interpreter(PY36)

    pex_file = os.path.join(str(tmpdir), "pex")

    requirement = "subprocess32==3.2.7; python_version<'3'"
    results = run_pex_command(
        args=["--python", python27, "--python", python36, requirement, "-o", pex_file]
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

    py36_interpreter = PythonInterpreter.from_binary(python36)
    output, returncode = run_simple_pex(
        pex_file,
        args=["-c", "import subprocess"],
        interpreter=py36_interpreter,
    )
    assert 0 == returncode

    py36_interpreter = PythonInterpreter.from_binary(python36)
    output, returncode = run_simple_pex(
        pex_file,
        args=["-c", "import subprocess32"],
        interpreter=py36_interpreter,
    )
    assert (
        1 == returncode
    ), "Expected subprocess32 to be present in the PEX file but not activated for Python 3."


def test_2020_resolver_engaged_issues_1179():
    # type: () -> None

    # The Pip legacy resolver cannot solve the following requirements but the 2020 resolver can.
    # Use this fact to prove we're plumbing Pip resolver version arguments correctly.
    pex_args = ["boto3==1.15.6", "botocore>1.17<1.18.7", "--", "-c", "import boto3"]

    results = run_pex_command(args=["--resolver-version", "pip-legacy-resolver"] + pex_args)
    results.assert_failure()
    assert "Failed to resolve compatible distributions:" in results.error
    assert "1: boto3==1.15.6 requires botocore<1.19.0,>=1.18.6 but " in results.error

    run_pex_command(args=["--resolver-version", "pip-2020-resolver"] + pex_args).assert_success()
