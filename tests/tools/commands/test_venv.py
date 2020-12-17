# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
import tempfile
from subprocess import CalledProcessError
from textwrap import dedent

import pytest

from pex.common import temporary_dir, touch
from pex.executor import Executor
from pex.testing import run_pex_command
from pex.tools.commands.virtualenv import Virtualenv
from pex.typing import TYPE_CHECKING
from pex.util import named_temporary_file

if TYPE_CHECKING:
    from typing import Callable, Tuple, Any, Dict, Optional, Iterable

    CreatePexVenv = Callable[[Tuple[str, ...]], Virtualenv]


FABRIC_VERSION = "2.5.0"


@pytest.fixture(scope="module")
def pex():
    # type: () -> str
    with temporary_dir() as tmpdir:
        pex_path = os.path.join(tmpdir, "fabric.pex")

        src_dir = os.path.join(tmpdir, "src")
        touch(os.path.join(src_dir, "user/__init__.py"))
        touch(os.path.join(src_dir, "user/package/__init__.py"))

        # N.B.: --unzip just speeds up runs 2+ of the pex file and is otherwise not relevant to
        # these tests.
        run_pex_command(
            args=[
                "fabric=={}".format(FABRIC_VERSION),
                "-c",
                "fab",
                "--sources-directory",
                src_dir,
                "-o",
                pex_path,
                "--unzip",
                "--include-tools",
            ]
        )
        yield os.path.realpath(pex_path)


def make_env(**kwargs):
    # type: (**Any) -> Dict[str, str]
    env = os.environ.copy()
    env.update((k, str(v)) for k, v in kwargs.items())
    return env


@pytest.fixture
def create_pex_venv(pex):
    # type: (str) -> CreatePexVenv
    with temporary_dir() as tmpdir:
        venv_dir = os.path.join(tmpdir, "venv")

        def _create_pex_venv(*options):
            # type: (*str) -> Virtualenv
            subprocess.check_call(
                args=[pex, "venv", venv_dir] + list(options or ()), env=make_env(PEX_TOOLS="1")
            )
            return Virtualenv(venv_dir)

        yield _create_pex_venv


def test_force(create_pex_venv):
    # type: (CreatePexVenv) -> None
    venv = create_pex_venv("--pip")
    venv.interpreter.execute(args=["-m", "pip", "install", "ansicolors==1.1.8"])
    venv.interpreter.execute(args=["-c", "import colors"])

    with pytest.raises(CalledProcessError):
        create_pex_venv()

    venv_force = create_pex_venv("--force")
    # The re-created venv should have no ansicolors installed like the prior venv.
    with pytest.raises(Executor.NonZeroExit):
        venv_force.interpreter.execute(args=["-c", "import colors"])
    # The re-created venv should have no pip installed either.
    with pytest.raises(Executor.NonZeroExit):
        venv.interpreter.execute(args=["-m", "pip", "install", "ansicolors==1.1.8"])


def execute_venv_pex_interpreter(
    venv,  # type: Virtualenv
    code=None,  # type: Optional[str]
    extra_args=(),  # type: Iterable[str]
    **extra_env  # type: Any
):
    # type: (...) -> Tuple[int, str, str]
    process = subprocess.Popen(
        args=[venv.join_path("pex")] + list(extra_args),
        env=make_env(PEX_INTERPRETER=True, **extra_env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
    )
    stdout, stderr = process.communicate(input=None if code is None else code.encode())
    return process.returncode, stdout.decode("utf-8"), stderr.decode("utf-8")


def expected_file_path(
    venv,  # type: Virtualenv
    package,  # type: str
):
    # type: (...) -> str
    return os.path.realpath(
        os.path.join(
            venv.site_packages_dir,
            os.path.sep.join(package.split(".")),
            "__init__.{ext}".format(ext="pyc" if venv.interpreter.version[0] == 2 else "py"),
        )
    )


def parse_fabric_version_output(output):
    # type: (str) -> Dict[str, str]
    return dict(line.split(" ", 1) for line in output.splitlines())


def test_venv_pex(create_pex_venv):
    # type: (CreatePexVenv) -> None
    venv = create_pex_venv()
    venv_pex = venv.join_path("pex")

    fabric_output = subprocess.check_output(args=[venv_pex, "-V"])

    # N.B.: `fab -V` output looks like so:
    # $ fab -V
    # Fabric 2.5.0
    # Paramiko 2.7.2
    # Invoke 1.4.1
    versions = parse_fabric_version_output(fabric_output.decode("utf-8"))
    assert FABRIC_VERSION == versions["Fabric"]

    invoke_version = "Invoke {}".format(versions["Invoke"])
    invoke_script_output = subprocess.check_output(
        args=[venv_pex, "-V"], env=make_env(PEX_SCRIPT="invoke")
    )
    assert invoke_version == invoke_script_output.decode("utf-8").strip()

    invoke_entry_point_output = subprocess.check_output(
        args=[venv_pex, "-V"],
        env=make_env(PEX_MODULE="invoke.main:program.run"),
    )
    assert invoke_version == invoke_entry_point_output.decode("utf-8").strip()

    pex_extra_sys_path = ["/dev/null", "Bob"]
    returncode, _, stderr = execute_venv_pex_interpreter(
        venv,
        code=dedent(
            """\
            from __future__ import print_function

            import os
            import sys


            def assert_equal(test_num, expected, actual):
                if expected == actual:
                    return
                print(
                    "[{{}}] Expected {{}} but got {{}}".format(test_num, expected, actual),
                    file=sys.stderr,
                )
                sys.exit(test_num)

            assert_equal(1, {pex_extra_sys_path!r}, sys.path[-2:])

            import fabric
            assert_equal(2, {fabric!r}, os.path.realpath(fabric.__file__))

            import user.package
            assert_equal(3, {user_package!r}, os.path.realpath(user.package.__file__))
            """.format(
                pex_extra_sys_path=pex_extra_sys_path,
                fabric=expected_file_path(venv, "fabric"),
                user_package=expected_file_path(venv, "user.package"),
            )
        ),
        PEX_EXTRA_SYS_PATH=os.pathsep.join(pex_extra_sys_path),
    )
    assert 0 == returncode, stderr


def test_binary_path(create_pex_venv):
    # type: (CreatePexVenv) -> None
    code = dedent(
        """\
        import errno
        import subprocess
        import sys

        # PEXed code should be able to find all (console) scripts on the $PATH when the venv is
        # created with --bin-path set, and the scripts should all run with the venv interpreter in
        # order to find their code.

        def try_invoke(*args):
            try:
                subprocess.check_call(list(args))
                return 0
            except OSError as e:
                if e.errno == errno.ENOENT:
                    # This is what we expect when scripts are not set up on PATH via --bin-path.
                    return 1
                return 2

        exit_code = try_invoke("fab", "-V")
        exit_code += 10 * try_invoke("inv", "-V")
        exit_code += 100 * try_invoke("invoke", "-V")
        sys.exit(exit_code)
        """
    )

    venv = create_pex_venv()
    returncode, stdout, stderr = execute_venv_pex_interpreter(
        venv, code=code, PATH=tempfile.gettempdir()
    )
    assert 111 == returncode, stdout + stderr

    venv_bin_path = create_pex_venv("-f", "--bin-path", "prepend")
    returncode, _, _ = execute_venv_pex_interpreter(
        venv_bin_path, code=code, PATH=tempfile.gettempdir()
    )
    assert 0 == returncode


def test_venv_pex_interpreter_special_modes(create_pex_venv):
    # type: (CreatePexVenv) -> None
    venv = create_pex_venv()

    # special mode execute module: -m module
    returncode, stdout, stderr = execute_venv_pex_interpreter(venv, extra_args=["-m"])
    assert 2 == returncode, stderr
    assert "" == stdout

    returncode, stdout, stderr = execute_venv_pex_interpreter(
        venv, extra_args=["-m", "fabric", "--version"]
    )
    assert 0 == returncode, stderr
    versions = parse_fabric_version_output(stdout)
    assert FABRIC_VERSION == versions["Fabric"]

    # special mode execute code string: -c <str>
    returncode, stdout, stderr = execute_venv_pex_interpreter(venv, extra_args=["-c"])
    assert 2 == returncode, stderr
    assert "" == stdout

    fabric_file_code = "import fabric, os; print(os.path.realpath(fabric.__file__))"
    expected_fabric_file_path = expected_file_path(venv, "fabric")

    returncode, stdout, stderr = execute_venv_pex_interpreter(
        venv, extra_args=["-c", fabric_file_code]
    )
    assert 0 == returncode, stderr
    assert expected_fabric_file_path == stdout.strip()

    # special mode execute stdin: -
    returncode, stdout, stderr = execute_venv_pex_interpreter(
        venv, code=fabric_file_code, extra_args=["-"]
    )
    assert 0 == returncode, stderr
    assert expected_fabric_file_path == stdout.strip()

    # special mode execute python file: <py file name>
    with named_temporary_file(prefix="code", suffix=".py", mode="w") as fp:
        fp.write(fabric_file_code)
        fp.close()
        returncode, stdout, stderr = execute_venv_pex_interpreter(
            venv, code=fabric_file_code, extra_args=[fp.name]
        )
        assert 0 == returncode, stderr
        assert expected_fabric_file_path == stdout.strip()
