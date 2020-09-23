# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess

import pytest

from pex.common import safe_mkdir, temporary_dir
from pex.executor import Executor
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable, List

TEST_EXECUTABLE = "/a/nonexistent/path/to/nowhere"
TEST_CMD_LIST = [TEST_EXECUTABLE, "--version"]
TEST_CMD_STR = " ".join(TEST_CMD_LIST)
TEST_CMD_PARAMETERS = [TEST_CMD_LIST, TEST_CMD_STR]
TEST_STDOUT = "testing stdout"
TEST_STDERR = "testing stder"
TEST_CODE = 3


def test_executor_open_process_wait_return():
    # type: () -> None
    process = Executor.open_process("exit 8", shell=True)
    exit_code = process.wait()
    assert exit_code == 8


def test_executor_open_process_communicate():
    # type: () -> None
    process = Executor.open_process(
        ["/bin/echo", "-n", "hello"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = process.communicate()
    assert stdout.decode("utf-8") == "hello"
    assert stderr.decode("utf-8") == ""


def test_executor_execute():
    # type: () -> None
    assert Executor.execute("/bin/echo -n stdout >&1", shell=True) == ("stdout", "")
    assert Executor.execute("/bin/echo -n stderr >&2", shell=True) == ("", "stderr")
    assert Executor.execute("/bin/echo -n TEST | tee /dev/stderr", shell=True) == ("TEST", "TEST")
    assert Executor.execute(["/bin/echo", "hello"]) == ("hello\n", "")
    assert Executor.execute(["/bin/echo", "-n", "hello"]) == ("hello", "")
    assert Executor.execute("/bin/echo -n $HELLO", env={"HELLO": "hey"}, shell=True) == ("hey", "")


def test_executor_execute_zero():
    # type: () -> None
    Executor.execute("exit 0", shell=True)


@pytest.mark.parametrize("testable", [Executor.open_process, Executor.execute])
def test_executor_execute_not_found(testable):
    # type: (Callable) -> None
    with pytest.raises(Executor.ExecutableNotFound) as exc:
        testable(TEST_CMD_LIST)
    assert exc.value.executable == TEST_EXECUTABLE
    assert exc.value.cmd == TEST_CMD_LIST


@pytest.mark.parametrize("exit_code", [1, 127, -1])
def test_executor_execute_nonzero(exit_code):
    # type: (int) -> None
    with pytest.raises(Executor.NonZeroExit) as exc:
        Executor.execute("exit %s" % exit_code, shell=True)

    if exit_code > 0:
        assert exc.value.exit_code == exit_code


@pytest.mark.parametrize("cmd", TEST_CMD_PARAMETERS)
def test_executor_exceptions_executablenotfound(cmd):
    # type: (List[str]) -> None
    exc_cause = OSError("test")
    exc = Executor.ExecutableNotFound(cmd=cmd, exc=exc_cause)
    assert exc.executable == TEST_EXECUTABLE
    assert exc.cmd == cmd
    assert exc.exc == exc_cause


@pytest.mark.parametrize("cmd", TEST_CMD_PARAMETERS)
def test_executor_exceptions_nonzeroexit(cmd):
    # type: (List[str]) -> None
    exc = Executor.NonZeroExit(cmd=cmd, exit_code=TEST_CODE, stdout=TEST_STDOUT, stderr=TEST_STDERR)
    assert exc.executable == TEST_EXECUTABLE
    assert exc.cmd == cmd
    assert exc.exit_code == TEST_CODE
    assert exc.stdout == TEST_STDOUT
    assert exc.stderr == TEST_STDERR


def test_executor_execute_dir():
    # type: () -> None
    with temporary_dir() as temp_dir:
        test_dir = os.path.realpath(os.path.join(temp_dir, "tmp"))
        safe_mkdir(test_dir)
        assert os.path.isdir(test_dir)
        with pytest.raises(Executor.ExecutionError) as e:
            Executor.execute(test_dir)
        assert test_dir in str(e)
