# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import errno
import os

from pex.compatibility import PY2, string
from pex.tracer import TRACER

if os.name == "posix" and PY2:
    try:
        # Use the subprocess backports if they're available for improved robustness.
        import subprocess32 as subprocess  # type: ignore[import]
    except ImportError:
        TRACER.log(
            "Please build pex with the subprocess32 module for more reliable requirement "
            "installation and interpreter execution."
        )
        import subprocess  # type: ignore[no-redef]
else:
    import subprocess  # type: ignore[no-redef]


class Executor(object):
    """Handles execution of subprocesses in a structured way."""

    class ExecutionError(Exception):
        """Indicates failure to execute."""

        def __init__(self, msg, cmd, exc=None):
            super(Executor.ExecutionError, self).__init__(  # noqa
                "%s while trying to execute `%s`" % (msg, cmd)
            )
            self.executable = cmd.split()[0] if isinstance(cmd, string) else cmd[0]
            self.cmd = cmd
            self.exc = exc

    class NonZeroExit(ExecutionError):
        """Indicates a non-zero exit code."""

        def __init__(self, cmd, exit_code, stdout, stderr):
            super(Executor.NonZeroExit, self).__init__(  # noqa
                "received exit code %s during execution of `%s`" % (exit_code, cmd), cmd
            )
            self.exit_code = exit_code
            self.stdout = stdout
            self.stderr = stderr

    class ExecutableNotFound(ExecutionError):
        """Indicates the executable was not found while attempting to execute."""

        def __init__(self, cmd, exc):
            super(Executor.ExecutableNotFound, self).__init__(  # noqa
                "caught %r while trying to execute `%s`" % (exc, cmd), cmd
            )
            self.exc = exc

    @classmethod
    def open_process(cls, cmd, **kwargs):
        """Opens a process object via subprocess.Popen().

        :param string|list cmd: A list or string representing the command to run.
        :param **kwargs: Additional kwargs to pass through to subprocess.Popen.
        :return: A `subprocess.Popen` object.
        :raises: `Executor.ExecutableNotFound` when the executable requested to run does not exist.
        """
        assert len(cmd) > 0, "cannot execute an empty command!"

        try:
            return subprocess.Popen(cmd, **kwargs)
        except (IOError, OSError) as e:
            if e.errno == errno.ENOENT:
                raise cls.ExecutableNotFound(cmd, e)
            else:
                raise cls.ExecutionError(repr(e), cmd, e)

    @classmethod
    def execute(cls, cmd, stdin_payload=None, **kwargs):
        """Execute a command via subprocess.Popen and returns the stdio.

        :param string|list cmd: A list or string representing the command to run.
        :param string stdin_payload: A string representing the stdin payload, if any, to send.
        :param **kwargs: Additional kwargs to pass through to subprocess.Popen.
        :return: A tuple of strings representing (stdout, stderr), pre-decoded for utf-8.
        :raises: `Executor.ExecutableNotFound` when the executable requested to run does not exist.
                 `Executor.NonZeroExit` when the execution fails with a non-zero exit code.
        """
        process = cls.open_process(
            cmd=cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs
        )
        stdout_raw, stderr_raw = process.communicate(input=stdin_payload)
        # N.B. In cases where `stdout` or `stderr` is passed as parameters, these can be None.
        stdout = stdout_raw.decode("utf-8") if stdout_raw is not None else stdout_raw
        stderr = stderr_raw.decode("utf-8") if stderr_raw is not None else stderr_raw

        if process.returncode != 0:
            raise cls.NonZeroExit(cmd, process.returncode, stdout, stderr)

        return stdout, stderr
