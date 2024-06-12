# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os.path
import shutil
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.typing import TYPE_CHECKING
from testing import IS_PYPY, run_pex_command

if TYPE_CHECKING:
    from typing import Any, Iterable, List

parametrize_execution_mode_args = pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--venv"], id="VENV"),
    ],
)


parametrize_boot_mode_args = pytest.mark.parametrize(
    "boot_mode_args",
    [
        pytest.param([], id="PYTHON"),
        pytest.param(["--sh-boot"], id="SH_BOOT"),
    ],
)


@pytest.fixture
def exe(tmpdir):
    # type: (Any) -> str
    exe = os.path.join(str(tmpdir), "exe.py")
    with open(exe, "w") as fp:
        fp.write(
            dedent(
                """\
                import json
                import sys
                import warnings


                warnings.warn("If you don't eat your meat, you can't have any pudding!")
                json.dump(sys.argv[1:], sys.stdout)
                """
            )
        )
    return exe


def assert_exe_output(
    pex,  # type: str
    warning_expected,  # type: bool
    prefix_args=(),  # type: Iterable[str]
):
    process = subprocess.Popen(
        args=list(prefix_args) + [pex, "--foo", "bar"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate()
    error = stderr.decode("utf-8")
    assert 0 == process.returncode, error
    assert ["--foo", "bar"] == json.loads(stdout)
    assert warning_expected == (
        "If you don't eat your meat, you can't have any pudding!" in error
    ), error


@pytest.mark.skipif(
    IS_PYPY and sys.version_info[:2] < (3, 10),
    reason=(
        "Pex cannot retrieve the original argv when running under PyPy<3.10 which prevents "
        "passthrough."
    ),
)
@parametrize_execution_mode_args
@parametrize_boot_mode_args
def test_python_args_passthrough(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
    boot_mode_args,  # type: List[str]
    exe,  # type: str
):
    # type: (...) -> None

    default_shebang_pex = os.path.join(str(tmpdir), "default_shebang.pex")
    custom_shebang_pex = os.path.join(str(tmpdir), "custom_shebang.pex")
    pex_root = os.path.join(str(tmpdir), "pex_root")

    args = (
        execution_mode_args
        + boot_mode_args
        + [
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--exe",
            exe,
        ]
    )
    run_pex_command(args=args + ["-o", default_shebang_pex]).assert_success()
    run_pex_command(
        args=args
        + [
            "-o",
            custom_shebang_pex,
            "--python-shebang",
            "{python} -Wignore".format(python=sys.executable),
        ]
    ).assert_success()

    # N.B.: We execute tests in doubles after a cache nuke to exercise both cold and warm runs
    # which take different re-exec paths through the code that all need to preserve Python args.

    # The built-in python shebang args, if any, should be respected.
    shutil.rmtree(pex_root)
    assert_exe_output(default_shebang_pex, warning_expected=True)
    assert_exe_output(default_shebang_pex, warning_expected=True)
    assert_exe_output(custom_shebang_pex, warning_expected=False)
    assert_exe_output(custom_shebang_pex, warning_expected=False)

    # But they also should be able to be over-ridden.
    shutil.rmtree(pex_root)
    assert_exe_output(
        default_shebang_pex, prefix_args=[sys.executable, "-Wignore"], warning_expected=False
    )
    assert_exe_output(
        default_shebang_pex, prefix_args=[sys.executable, "-Wignore"], warning_expected=False
    )
    assert_exe_output(custom_shebang_pex, prefix_args=[sys.executable], warning_expected=True)
    assert_exe_output(custom_shebang_pex, prefix_args=[sys.executable], warning_expected=True)


@parametrize_execution_mode_args
@parametrize_boot_mode_args
def test_inject_python_args(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
    boot_mode_args,  # type: List[str]
    exe,  # type: str
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    pex_root = os.path.join(str(tmpdir), "pex_root")

    run_pex_command(
        args=execution_mode_args
        + boot_mode_args
        + [
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--exe",
            exe,
            "--inject-python-args=-W ignore",
            "-o",
            pex,
        ]
    ).assert_success()

    assert_exe_output(pex, warning_expected=False)
    assert_exe_output(pex, warning_expected=False)

    # N.B.: The original argv cannot be detected by Pex running under PyPy<3.10; so we expect
    # warnings to be turned off (the default sealed in by `--inject-python-args`). For all other
    # Pythons we support, these explicit command line Python args should be detected and trump the
    # injected args by dint of occurring later in the command line. In other words, the command line
    # should be as follows and Python is known to pick the last occurrence of the -W option:
    #
    #   python -W ignore -W always ...
    #
    warning_expected = not IS_PYPY or sys.version_info[:2] >= (3, 10)
    assert_exe_output(
        pex, prefix_args=[sys.executable, "-W", "always"], warning_expected=warning_expected
    )
    assert_exe_output(
        pex, prefix_args=[sys.executable, "-W", "always"], warning_expected=warning_expected
    )


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 10 if IS_PYPY else 9),
    reason=(
        "The effect of `-u` on the `sys.stdout.buffer` type used in this test is only "
        "differentiable from a lack of `-u` for these Pythons."
    ),
)
@parametrize_execution_mode_args
@parametrize_boot_mode_args
def test_issue_2422(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
    boot_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    pex_root = os.path.join(str(tmpdir), "pex_root")

    exe = os.path.join(str(tmpdir), "exe.py")
    with open(exe, "w") as fp:
        fp.write(
            dedent(
                """\
                import sys


                if __name__ == "__main__":
                    print(type(sys.stdout.buffer).__name__)
                """
            )
        )

    args = ["--pex-root", pex_root, "--runtime-pex-root", pex_root, "--exe", exe, "-o", pex]
    args.extend(execution_mode_args)
    args.extend(boot_mode_args)

    run_pex_command(args=args).assert_success()
    shutil.rmtree(pex_root)
    assert b"BufferedWriter\n" == subprocess.check_output(args=[sys.executable, exe])
    assert b"BufferedWriter\n" == subprocess.check_output(
        args=[pex]
    ), "Expected cold run to use buffered io."
    assert b"BufferedWriter\n" == subprocess.check_output(
        args=[pex]
    ), "Expected warm run to use buffered io."

    assert b"FileIO\n" == subprocess.check_output(
        args=[sys.executable, "-u", pex]
    ), "Expected explicit Python arguments to be honored."

    run_pex_command(args=args + ["--inject-python-args=-u"]).assert_success()
    shutil.rmtree(pex_root)
    assert b"FileIO\n" == subprocess.check_output(args=[sys.executable, "-u", exe])
    assert b"FileIO\n" == subprocess.check_output(
        args=[pex]
    ), "Expected cold run to use un-buffered io."
    assert b"FileIO\n" == subprocess.check_output(
        args=[pex]
    ), "Expected warm run to use un-buffered io."

    process = subprocess.Popen(
        args=[sys.executable, "-v", pex],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate()
    assert 0 == process.returncode
    assert b"FileIO\n" == stdout, "Expected injected Python arguments to be honored."
    assert b"import " in stderr, "Expected explicit Python arguments to be honored as well."
