# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import errno
import subprocess
from abc import abstractmethod
from threading import BoundedSemaphore, Event, Thread

from pex.compatibility import AbstractClass, Queue, cpu_count
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, Generic

if TYPE_CHECKING:
    from typing import Any, Callable, Iterable, Optional, Text, Tuple, TypeVar

    import attr  # vendor:skip

    _T = TypeVar("_T")
else:
    from pex.third_party import attr


class Job(object):
    """Represents a job spawned as a subprocess.

    Presents a similar API to `subprocess` except where noted.
    """

    class Error(Exception):
        """Indicates that a Job exited non-zero."""

        def __init__(
            self,
            pid,  # type: int
            command,  # type: Tuple[str, ...]
            exitcode,  # type: int
            stderr,  # type: Optional[Text]
            message,  # type: str
        ):
            # type: (...) -> None
            super(Job.Error, self).__init__(message)
            self.pid = pid
            self.command = command
            self.exitcode = exitcode
            self.stderr = stderr

    def __init__(
        self,
        command,  # type: Iterable[str]
        process,  # type: subprocess.Popen
        finalizer=None,  # type: Optional[Callable[[int], None]]
    ):
        # type: (...) -> None
        """
        :param command: The command used to spawn the job process.
        :param process: The spawned process handle.
        :param finalizer: An optional cleanup function to call exactly once with the process return
                          code when the underlying process terminates in the course of calling this
                          job's public methods.
        """
        self._command = tuple(command)
        self._process = process
        self._finalizer = finalizer

    def wait(self):
        # type: () -> None
        """Waits for the job to complete.

        :raises: :class:`Job.Error` if the job exited non-zero.
        """
        try:
            _, stderr = self._process.communicate()
            self._check_returncode(stderr)
        finally:
            self._finalize_job()

    def communicate(self, input=None):
        # type: (Optional[bytes]) -> Tuple[bytes, bytes]
        """Communicates with the job sending any input data to stdin and collecting stdout and
        stderr.

        :param input: Data to send to stdin of the job as per the `subprocess` API.
        :return: A tuple of the job's stdout and stderr as per the `subprocess` API.
        :raises: :class:`Job.Error` if the job exited non-zero.
        """
        try:
            stdout, stderr = self._process.communicate(input=input)
            self._check_returncode(stderr)
            return stdout, stderr
        finally:
            self._finalize_job()

    def kill(self):
        # type: () -> None
        """Terminates the job if it is still running.

        N.B.: This method is idempotent.
        """
        try:
            self._process.kill()
        except OSError as e:
            if e.errno != errno.ESRCH:
                raise e
        finally:
            self._finalize_job()

    def create_error(
        self,
        msg,  # type: str
        stderr=None,  # type: Optional[bytes]
    ):
        # type: (...) -> Job.Error
        """Creates an error with this Job's details.

        :param msg: The message for the error.
        :param stderr: Any stderr output captured from the job.
        :return: A job error.
        """
        err = None
        if stderr:
            err = stderr.decode("utf-8")
            msg += "\nSTDERR:\n{}".format(err)
        raise self.Error(
            pid=self._process.pid,
            command=self._command,
            exitcode=self._process.returncode,
            stderr=err,
            message=msg,
        )

    def _finalize_job(self):
        if self._finalizer is not None:
            self._finalizer(self._process.returncode)
            self._finalizer = None

    def _check_returncode(self, stderr=None):
        # type: (Optional[bytes]) -> None
        if self._process.returncode != 0:
            msg = "Executing {} failed with {}".format(
                " ".join(self._command), self._process.returncode
            )
            raise self.create_error(msg, stderr=stderr)

    def __str__(self):
        # type: () -> str
        return "pid: {pid} -> {command}".format(
            pid=self._process.pid, command=" ".join(self._command)
        )


class SpawnedJob(Generic["_T"]):
    """A handle to a spawned :class:`Job` and its associated result."""

    @classmethod
    def completed(cls, result):
        # type: (_T) -> SpawnedJob[_T]
        """Wrap an already completed result in a SpawnedJob.

        The returned job will no-op when `kill` is called since the job is already completed.

        :param result: The completed result.
        :return: A spawned job whose result is already complete.
        """

        class Completed(SpawnedJob):
            def await_result(self):
                # type: () -> _T
                return result

            def kill(self):
                # type: () -> None
                pass

            def __repr__(self):
                # type: () -> str
                return "SpawnedJob.completed({!r})".format(result)

        return Completed()

    @classmethod
    def wait(
        cls,
        job,  # type: Job
        result,  # type: _T
    ):
        # type: (...) -> SpawnedJob[_T]
        """Wait for the job to complete and return a fixed result upon success.

        :param job: The spawned job.
        :param result: The fixed success result.
        :return: A spawned job whose result is a side effect of the job (a written file, a populated
                 directory, etc.).
        """
        return cls.and_then(job, lambda: result)

    @classmethod
    def and_then(
        cls,
        job,  # type: Job
        result_func,  # type: Callable[[], _T]
    ):
        # type: (...) -> SpawnedJob[_T]
        """Wait for the job to complete and return a result derived from its side effects.

        :param job: The spawned job.
        :param result_func: A function that will be called to produce the result upon job success.
        :return: A spawned job whose result is derived from a side effect of the job (a written
                 file, a populated directory, etc.).
        """

        class AndThen(SpawnedJob):
            def await_result(self):
                # type: () -> _T
                job.wait()
                return result_func()

            def kill(self):
                # type: () -> None
                job.kill()

            def __repr__(self):
                # type: () -> str
                return "SpawnedJob.and_then({!r})".format(job)

        return AndThen()

    @classmethod
    def stdout(
        cls,
        job,  # type: Job
        result_func,  # type: Callable[[bytes], _T]
        input=None,  # type: Optional[bytes]
    ):
        # type: (...) -> SpawnedJob[_T]
        """Wait for the job to complete and return a result derived from its stdout.

        :param job: The spawned job.
        :param result_func: A function taking the stdout byte string collected from the spawned job
                            and returning the desired result.
        :param input: Optional input stream data to pass to the process as per the
                      `subprocess.Popen.communicate` API.
        :return: A spawned job whose result is derived from stdout contents.
        """

        class Stdout(SpawnedJob):
            def await_result(self):
                # type: () -> _T
                stdout, _ = job.communicate(input=input)
                return result_func(stdout)

            def kill(self):
                # type: () -> None
                job.kill()

            def __repr__(self):
                # type: () -> str
                return "SpawnedJob.stdout({!r})".format(job)

        return Stdout()

    @classmethod
    def file(
        cls,
        job,  # type: Job
        output_file,  # type: str
        result_func,  # type: Callable[[bytes], _T]
        input=None,  # type: Optional[bytes]
    ):
        # type: (...) -> SpawnedJob[_T]
        """Wait for the job to complete and return a result derived from a file the job creates.

        :param job: The spawned job.
        :param output_file: The path of the file the job will create.
        :param result_func: A function taking the byte contents of the file the spawned job
                            created and returning the desired result.
        :param input: Optional input stream data to pass to the process as per the
                      `subprocess.Popen.communicate` API.
        :return: A spawned job whose result is derived from the contents of a file it creates.
        """

        def _read_file(stderr=None):
            # type: (Optional[bytes]) -> bytes
            try:
                with open(output_file, "rb") as fp:
                    return fp.read()
            except (OSError, IOError) as e:
                raise job.create_error(
                    "Expected job to create file {output_file!r} but it did not exist or could not "
                    "be read: {err}".format(output_file=output_file, err=e),
                    stderr=stderr,
                )

        class File(SpawnedJob):
            def await_result(self):
                # type: () -> _T
                _, stderr = job.communicate(input=input)
                return result_func(_read_file(stderr=stderr))

            def kill(self):
                # type: () -> None
                job.kill()

            def __repr__(self):
                # type: () -> str
                return "SpawnedJob.file({job!r}, output_file={output_file!r})".format(
                    job=job, output_file=output_file
                )

        return File()

    def await_result(self):
        # type: () -> _T
        """Waits for the spawned job to complete and returns its result."""
        raise NotImplementedError()

    def kill(self):
        # type: () -> None
        """Terminates the spawned job if it's not already complete."""
        raise NotImplementedError()


# If `cpu_count` fails, we default to 2. This is relatively arbitrary, based on what seems to be
# common in CI.
_CPU_COUNT = cpu_count() or 2
_ABSOLUTE_MAX_JOBS = _CPU_COUNT * 2


DEFAULT_MAX_JOBS = _CPU_COUNT
"""The default maximum number of parallel jobs PEX should use."""


def _sanitize_max_jobs(max_jobs=None):
    assert max_jobs is None or isinstance(max_jobs, int)
    if max_jobs is None or max_jobs <= 0:
        return DEFAULT_MAX_JOBS
    else:
        return min(max_jobs, _ABSOLUTE_MAX_JOBS)


class ErrorHandler(AbstractClass):  # type: ignore[valid-type, misc]
    """Handles errors encountered in the context of spawning and awaiting the result of a `Job`."""

    @classmethod
    def spawn_error_message(cls, item, exception):
        return "Failed to spawn a job for {item}: {exception}".format(
            item=item, exception=exception
        )

    @classmethod
    def job_error_message(cls, _item, job_error):
        return "pid {pid} -> {command} exited with {exitcode} and STDERR:\n{stderr}".format(
            pid=job_error.pid,
            command=" ".join(job_error.command),
            exitcode=job_error.exitcode,
            stderr=job_error.stderr,
        )

    @abstractmethod
    def handle_spawn_error(self, item, exception):
        """Handle an error encountered spawning a job.

        :param item: The item that was the input for the spawned job.
        :param exception: The exception encountered attempting to spawn the job for `item`.
        :type exception: :class:`Exception`
        :returns: A value to represent the failed processing of the item or else `None` to skip
                  processing of the item altogether.
        :raise: To indicate all item processing should be cancelled and the exception raised.
        """

    @abstractmethod
    def handle_job_error(self, item, job_error):
        """Handle a job that exits unsuccessfully.

        :param item: The item that was the input for the spawned job.
        :param job_error: An error capturing the details of the job failure.
        :type job_error: :class:`Job.Error`
        :returns: A value to represent the failed processing of the item or else `None` to skip
                  processing of the item altogether.
        :raise: To indicate all item processing should be cancelled and the exception raised.
        """


class Raise(ErrorHandler):
    """Re-raises errors encountered spawning or awaiting the result of a `Job`."""

    def __init__(self, raise_type):
        """
        :param raise_type: The type of exception to raise when a `Job` fails.
        :type raise_type: An :class:`Exception` subclass.
        """
        self._raise_type = raise_type

    def handle_spawn_error(self, item, exception):
        raise self._raise_type(self.spawn_error_message(item, exception))

    def handle_job_error(self, item, job_error):
        raise self._raise_type(self.job_error_message(item, job_error))


class Retain(ErrorHandler):
    """Retains errors encountered spawning or awaiting the result of a `Job`.

    The retained errors are returned as the result of the failed `Job` in the form of (item, error)
    tuples. In the case of a spawn failure, the error item is likely an instance of `OSError`. In
    the case of the `Job` failing (exiting non-zero), the error will be an instance of `Job.Error`.
    """

    def handle_spawn_error(self, item, exception):
        return item, exception

    def handle_job_error(self, item, job_error):
        return item, job_error


class Log(ErrorHandler):
    """Logs errors encountered spawning or awaiting the result of a `Job`."""

    def handle_spawn_error(self, item, exception):
        TRACER.log(self.spawn_error_message(item, exception))
        return None

    def handle_job_error(self, item, job_error):
        TRACER.log(self.job_error_message(item, job_error))
        return None


def execute_parallel(inputs, spawn_func, error_handler=None, max_jobs=None):
    """Execute jobs for the given inputs in parallel.

    :param int max_jobs: The maximum number of parallel jobs to spawn.
    :param inputs: An iterable of the data to parallelize over `spawn_func`.
    :param spawn_func: A function taking a single input and returning a :class:`SpawnedJob`.
    :param error_handler: An optional :class:`ErrorHandler`, defaults to :class:`Log`.
    :returns: An iterator over the spawned job results as they come in.
    :raises: A `raise_type` exception if any individual job errors and `raise_type` is not `None`.
    """
    error_handler = error_handler or Log()
    if not isinstance(error_handler, ErrorHandler):
        raise ValueError(
            "Given error_handler {} of type {}, expected an {}".format(
                error_handler, type(error_handler), ErrorHandler
            )
        )

    size = _sanitize_max_jobs(max_jobs)
    TRACER.log(
        "Spawning a maximum of {} parallel jobs to process:\n  {}".format(
            size, "\n  ".join(map(str, inputs))
        ),
        V=9,
    )

    @attr.s(frozen=True)
    class Spawn(object):
        item = attr.ib()  # type: Any
        spawned_job = attr.ib()  # type: SpawnedJob

    @attr.s(frozen=True)
    class SpawnError(object):
        item = attr.ib()  # type: Any
        error = attr.ib()  # type: Exception

    stop = Event()  # Used as a signal to stop spawning further jobs once any one job fails.
    job_slots = BoundedSemaphore(value=size)
    done_sentinel = object()
    spawn_queue = Queue()  # Queue[Union[Spawn, SpawnError, Literal[done_sentinel]]]

    def spawn_jobs():
        for item in inputs:
            if stop.is_set():
                break
            job_slots.acquire()
            try:
                result = Spawn(item, spawn_func(item))
            except Exception as e:
                result = SpawnError(item, e)
            finally:
                spawn_queue.put(result)
        spawn_queue.put(done_sentinel)

    spawner = Thread(name="PEX Parallel Job Spawner", target=spawn_jobs)
    spawner.daemon = True
    spawner.start()

    error = None
    while True:
        spawn_result = spawn_queue.get()

        if spawn_result is done_sentinel:
            if error:
                raise error
            return

        try:
            if isinstance(spawn_result, SpawnError):
                try:
                    result = error_handler.handle_spawn_error(spawn_result.item, spawn_result.error)
                    if result is not None:
                        yield result
                except Exception as e:
                    # Fail fast and proceed to kill all outstanding spawned jobs.
                    stop.set()
                    error = e
            elif (
                error is not None
            ):  # I.E.: `item` is not an exception, but there was a prior exception.
                spawn_result.spawned_job.kill()
            else:
                try:
                    yield spawn_result.spawned_job.await_result()
                except Job.Error as e:
                    try:
                        result = error_handler.handle_job_error(spawn_result.item, e)
                        if result is not None:
                            yield result
                    except Exception as e:
                        # Fail fast and proceed to kill all outstanding spawned jobs.
                        stop.set()
                        error = e
        finally:
            job_slots.release()
