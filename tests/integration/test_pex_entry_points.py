# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
from textwrap import dedent

from pex.common import safe_open
from pex.typing import TYPE_CHECKING
from testing import make_project, run_pex_command

if TYPE_CHECKING:
    from typing import Any


def test_style_mutex():
    result = run_pex_command(args=["-e", "module:func", "-c", "script"])
    result.assert_failure()
    assert (
        "error: argument -c/--script/--console-script: not allowed with argument "
        "-m/-e/--entry-point"
    ) in result.error

    result = run_pex_command(args=["-e", "module:func", "--exe", "exe"])
    result.assert_failure()
    assert (
        "error: argument --exe/--executable/--python-script: not allowed with argument "
        "-m/-e/--entry-point"
    ) in result.error

    result = run_pex_command(args=["-c", "script", "--exe", "exe"])
    result.assert_failure()
    assert (
        "error: argument --exe/--executable/--python-script: not allowed with argument "
        "-c/--script/--console-script"
    ) in result.error


def test_script(tmpdir):
    # type: (Any) -> None

    pex = os.path.join(str(tmpdir), "pex")

    # N.B.: `make_project` defines setuptools `scripts` for "hello_world" and "shell_script".
    with make_project(
        entry_points={"console_scripts": ["my_app = my_project.my_module:do_something"]},
    ) as project:

        run_pex_command(args=[project, "-c", "my_app", "-o", pex]).assert_success()
        assert b"hello world!\n" == subprocess.check_output(args=[pex])

        run_pex_command(args=[project, "-c", "hello_world", "-o", pex]).assert_success()
        assert b"hello world from py script!\n" == subprocess.check_output(args=[pex])

        run_pex_command(args=[project, "-c", "shell_script", "-o", pex]).assert_success()
        assert b"hello world from shell script\n" == subprocess.check_output(args=[pex])


def test_entry_point(tmpdir):
    # type: (Any) -> None

    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "my_library.py"), "w") as fp:
        fp.write("CONSTANT = 42")

    with safe_open(os.path.join(src, "my_ep.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import os
                import sys

                from my_library import CONSTANT


                def constant():
                    return CONSTANT


                if __name__ == "__main__":
                    sys.exit(CONSTANT // 2)
                """
            )
        )

    pex = os.path.join(str(tmpdir), "pex")

    run_pex_command(args=["-D", src, "-m", "my_ep", "-o", pex]).assert_success()
    assert 21 == subprocess.Popen(args=[pex]).wait()

    run_pex_command(args=["-D", src, "-e", "my_ep", "-o", pex]).assert_success()
    assert 21 == subprocess.Popen(args=[pex]).wait()

    run_pex_command(args=["-D", src, "-e", "my_ep:constant", "-o", pex]).assert_success()
    assert 42 == subprocess.Popen(args=[pex]).wait()


def test_executable(tmpdir):
    # type: (Any) -> None

    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "my_library.py"), "w") as fp:
        fp.write("CONSTANT = 42")

    executable = os.path.join(str(tmpdir), "bin", "my-executable.py")
    with safe_open(executable, "w") as fp:
        fp.write(
            dedent(
                """\
                import os
                import sys

                from my_library import CONSTANT


                if __name__ == "__main__":
                    sys.exit(CONSTANT)
                """
            )
        )

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(args=["-D", src, "--executable", executable, "-o", pex]).assert_success()
    assert 42 == subprocess.Popen(args=[pex]).wait()
