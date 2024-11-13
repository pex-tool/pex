# Copyright 2019 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import errno
import functools
import multiprocessing
import os
import subprocess
import time
from abc import abstractmethod
from collections import defaultdict
from contextlib import contextmanager
from threading import BoundedSemaphore, Event, Thread

from pex.common import pluralize
from pex.compatibility import Queue, cpu_count
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, Generic

if TYPE_CHECKING:
    from typing import (
        Any,
        Callable,
        DefaultDict,
        Iterable,
        Iterator,
        List,
        Optional,
        Protocol,
        Text,
        Tuple,
        TypeVar,
        Union,
    )

    import attr  # vendor:skip

    _I = TypeVar("_I")
    _O = TypeVar("_O")
    _T = TypeVar("_T")
    _S = TypeVar("_S")
    _SE = TypeVar("_SE")
    _JE = TypeVar("_JE")
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
            context=None,  # type: Optional[str]
        ):
            # type: (...) -> None
            super(Job.Error, self).__init__(
                "{ctx}: {msg}".format(ctx=context, msg=message) if context else message
            )
            self.pid = pid
            self.command = command
            self.exitcode = exitcode
            self.stderr = stderr
            self._context = context

        def contextualized_stderr(self):
            # type: () -> Iterator[Text]
            if self.stderr:
                for line in self.stderr.splitlines():
                    if not self._context:
                        yield line
                    else:
                        yield "{ctx}: {line}".format(ctx=self._context, line=line)

    def __init__(
        self,
        command,  # type: Iterable[str]
        process,  # type: subprocess.Popen
        finalizer=None,  # type: Optional[Callable[[int], None]]
        context=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        """
        :param command: The command used to spawn the job process.
        :param process: The spawned process handle.
        :param finalizer: An optional cleanup function to call exactly once with the process return
                          code when the underlying process terminates in the course of calling this
                          job's public methods.
        :param context: An optional context labeling the job that will be used to decorate error
                        information.
        """
        self._command = tuple(command)
        self._process = process
        self._finalizer = finalizer
        self._context = context

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
            context=self._context,
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

    def map(self, func):
        # type: (Callable[[_T], _S]) -> SpawnedJob[_S]

        class Map(SpawnedJob):
            def await_result(me):
                # type: () -> _S
                return func(self.await_result())

            def kill(me):
                # type: () -> None
                self.kill()

            def __repr__(me):
                # type: () -> str
                return "{job}.map({func})".format(job=self, func=func)

        return Map()


# If `cpu_count` fails, we default to 2. This is relatively arbitrary, based on what seems to be
# common in CI.
_CPU_COUNT = cpu_count() or 2
_ABSOLUTE_MAX_JOBS = _CPU_COUNT * 2


DEFAULT_MAX_JOBS = _CPU_COUNT
"""The default maximum number of parallel jobs PEX should use."""


def _sanitize_max_jobs(max_jobs=None):
    # type: (Optional[int]) -> int
    if max_jobs is None or max_jobs <= 0:
        return DEFAULT_MAX_JOBS
    else:
        return min(max_jobs, _ABSOLUTE_MAX_JOBS)


class ErrorHandler(Generic["_I", "_SE", "_JE"]):
    """Handles errors encountered in the context of spawning and awaiting the result of a `Job`."""

    @classmethod
    def spawn_error_message(
        cls,
        item,  # type: _I
        exception,  # type: Exception
    ):
        # type: (...) -> str
        return "Failed to spawn a job for {item}: {exception}".format(
            item=item, exception=exception
        )

    @classmethod
    def job_error_message(
        cls,
        _item,  # type: _I
        job_error,  # type: Job.Error
    ):
        # type: (...) -> str
        return "pid {pid} -> {command} exited with {exitcode} and STDERR:\n{stderr}".format(
            pid=job_error.pid,
            command=" ".join(job_error.command),
            exitcode=job_error.exitcode,
            stderr="\n".join(job_error.contextualized_stderr()),
        )

    @abstractmethod
    def handle_spawn_error(
        self,
        item,  # type: _I
        exception,  # type: Exception
    ):
        # type: (...) -> _SE
        """Handle an error encountered spawning a job.

        :param item: The item that was the input for the spawned job.
        :param exception: The exception encountered attempting to spawn the job for `item`.
        :type exception: :class:`Exception`
        :returns: A value to represent the failed processing of the item or else `None` to skip
                  processing of the item altogether.
        :raise: To indicate all item processing should be cancelled and the exception raised.
        """

    @abstractmethod
    def handle_job_error(
        self,
        item,  # type: _I
        job_error,  # type: Job.Error
    ):
        # type: (...) -> _JE
        """Handle a job that exits unsuccessfully.

        :param item: The item that was the input for the spawned job.
        :param job_error: An error capturing the details of the job failure.
        :type job_error: :class:`Job.Error`
        :returns: A value to represent the failed processing of the item or else `None` to skip
                  processing of the item altogether.
        :raise: To indicate all item processing should be cancelled and the exception raised.
        """


class Raise(ErrorHandler["_I", "_O", "_O"], Generic["_I", "_O"]):
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


class Retain(ErrorHandler["_I", "Tuple[_I, Exception]", "Tuple[_I, Job.Error]"], Generic["_I"]):
    """Retains errors encountered spawning or awaiting the result of a `Job`.

    The retained errors are returned as the result of the failed `Job` in the form of (item, error)
    tuples. In the case of a spawn failure, the error item is likely an instance of `OSError`. In
    the case of the `Job` failing (exiting non-zero), the error will be an instance of `Job.Error`.
    """

    def handle_spawn_error(self, item, exception):
        return item, exception

    def handle_job_error(self, item, job_error):
        return item, job_error


class Log(ErrorHandler["_I", "_O", "_O"], Generic["_I", "_O"]):
    """Logs errors encountered spawning or awaiting the result of a `Job`."""

    def handle_spawn_error(self, item, exception):
        TRACER.log(self.spawn_error_message(item, exception))
        return None

    def handle_job_error(self, item, job_error):
        TRACER.log(self.job_error_message(item, job_error))
        return None


def execute_parallel(
    inputs,  # type: Iterable[_I]
    spawn_func,  # type: Callable[[_I], SpawnedJob[_O]]
    error_handler=None,  # type: Optional[ErrorHandler[_I, _SE, _JE]]
    max_jobs=None,  # type: Optional[int]
):
    # type: (...) -> Iterator[Union[_O, _SE, _JE]]
    """Execute jobs for the given inputs in parallel subprocesses.

    :param int max_jobs: The maximum number of parallel jobs to spawn.
    :param inputs: An iterable of the data to parallelize over `spawn_func`.
    :param spawn_func: A function taking a single input and returning a :class:`SpawnedJob`.
    :param error_handler: An optional :class:`ErrorHandler`, defaults to :class:`Log`.
    :returns: An iterator over the spawned job results as they come in.
    :raises: A `raise_type` exception if any individual job errors and `raise_type` is not `None`.
    """
    handler = (
        error_handler or Log["_I", "_O"]()
    )  # type: Union[ErrorHandler[_I, _SE, _JE], Log[_I, _O]]
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

    class DoneSentinel(object):
        pass

    done_sentinel = DoneSentinel()
    spawn_queue = Queue()  # type: Queue[Union[Spawn, SpawnError, DoneSentinel]]

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

    @contextmanager
    def spawned_jobs():
        spawner = Thread(name="PEX Parallel Job Spawner", target=spawn_jobs)
        spawner.daemon = True
        spawner.start()
        try:
            yield
        finally:
            stop.set()
            # N.B.: We want to ensure, no matter what, the spawn_jobs loop above spins at least once
            # so that it can see stop is set and exit in the case it is currently blocked on a put
            # waiting for a job slot.
            try:
                job_slots.release()
            except ValueError:
                # From the BoundedSemaphore doc:
                #
                #   If the number of releases exceeds the number of acquires,
                #   raise a ValueError.
                #
                # In the normal case there will be no job_slots to release; so we expect the
                # BoundedSemaphore to raise here. We're guarding against the abnormal case where
                # there is a bug in the state machine implied by the execute_parallel code.
                pass
            spawner.join()

    with spawned_jobs():
        error = None
        while True:
            spawn_result = spawn_queue.get()

            if isinstance(spawn_result, DoneSentinel):
                if error:
                    raise error
                return

            try:
                if isinstance(spawn_result, SpawnError):
                    try:
                        se_result = handler.handle_spawn_error(
                            spawn_result.item, spawn_result.error
                        )
                        if se_result is not None:
                            yield se_result
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
                            je_result = handler.handle_job_error(spawn_result.item, e)
                            if je_result is not None:
                                yield je_result
                        except Exception as e:
                            # Fail fast and proceed to kill all outstanding spawned jobs.
                            stop.set()
                            error = e
            finally:
                job_slots.release()


if TYPE_CHECKING:

    class Comparable(Protocol):
        def __lt__(self, other):
            # type: (Any) -> bool
            pass


now = getattr(time, "perf_counter", getattr(time, "clock", time.time))  # type: Callable[[], float]


def _apply_function(
    function,  # type: Callable[[_I], _O]
    input_item,  # type: _I
):
    # type: (...) -> Tuple[int, _O, float]
    start = now()
    result = function(input_item)
    return os.getpid(), result, now() - start


if TYPE_CHECKING:

    class Pool(Protocol):
        def imap_unordered(
            self,
            func,  # type: Callable[[_I], _O]
            iterable,  # type: Iterable[_I]
            chunksize=1,  # type: int
        ):
            # type: (...) -> Iterator[_O]
            pass

        def close(self):
            # type: () -> None
            pass

        def join(self):
            # type: () -> None
            pass


@contextmanager
def _mp_pool(size):
    # type: (int) -> Iterator[Pool]

    pool = multiprocessing.Pool(processes=size)
    try:
        yield pool
    finally:
        pool.close()
        pool.join()


# This is derived from experiment and backed up by multiprocessing internal default chunk size of
# 4 for chunked mapping. The overhead of setting up and bookkeeping the multiprocessing pool
# processes and communication pipes seems to be worth if at least 4 items are processed per slot.
MULTIPROCESSING_DEFAULT_MIN_AVERAGE_LOAD = 4


def iter_map_parallel(
    inputs,  # type: Iterable[_I]
    function,  # type: Callable[[_I], _O]
    max_jobs=None,  # type: Optional[int]
    min_average_load=MULTIPROCESSING_DEFAULT_MIN_AVERAGE_LOAD,  # type: int
    costing_function=None,  # type: Optional[Callable[[_I], Comparable]]
    result_render_function=None,  # type: Optional[Callable[[_O], Any]]
    noun="item",  # type: str
    verb="process",  # type: str
    verb_past="processed",  # type: str
):
    # type: (...) -> Iterator[_O]
    """Enhanced `multiprocessing.Pool.imap_unordered` that optimizes pool size and input ordering.

    :param inputs: The items to process with `function`.
    :param function: A function that takes a single argument from `inputs` and returns a result.
    :param max_jobs: The maximum number of Python processes to spawn to service the `inputs`.
    :param min_average_load: The minimum avg. number of inputs each Python process should service.
    :param costing_function: A function that can estimate the cost of processing each input.
    :param result_render_function: A function that can take a result from `function` and render an
                                   identifier for it.
    :param noun: A noun indicating what the input type is; "item" by default.
    :param verb: A verb indicating what the function does; "process" by default.
    :param verb_past: The past tense of `verb`; "processed" by default.
    :return: An iterator over the mapped results.
    """
    input_items = list(inputs)
    if not input_items:
        return

    if costing_function is not None:
        # We ensure no job slot is so unlucky as to get all the biggest jobs and thus become an
        # un-necessarily long pole by sorting based on cost. Some examples to illustrate the effect
        # using 6 input items and 2 job slots:
        #
        # 1.) Random worst case ordering:
        #         [9, 1, 1, 1, 1, 10] -> slot1[9] slot2[1, 1, 1, 1, 10]: 14 long pole
        #     Sorted becomes:
        #         [10, 9, 1, 1, 1, 1] -> slot1[10, 1, 1] slot2[9, 1, 1]: 12 long pole
        # 2.) Random worst case ordering:
        #         [6, 4, 3, 10, 1, 1] -> slot1[6, 10] slot2[4, 3, 1, 1]: 16 long pole
        #     Sorted becomes:
        #         [10, 6, 4, 3, 1, 1] -> slot1[10, 3] slot2[6, 4, 1, 1]: 13 long pole
        #
        input_items.sort(key=costing_function, reverse=True)

    # We want each of the job slots above to process MULTIPROCESSING_DEFAULT_MIN_AVERAGE_LOAD on
    # average in order to overcome multiprocessing overheads. Of course, if there are fewer
    # available cores than that or the user has pinned max jobs lower, we clamp to that. Finally, we
    # always want at least two slots to ensure we process input items in parallel.
    pool_size = max(2, min(len(input_items) // min_average_load, _sanitize_max_jobs(max_jobs)))

    apply_function = functools.partial(_apply_function, function)

    slots = defaultdict(list)  # type: DefaultDict[int, List[float]]
    with TRACER.timed(
        "Using {pool_size} parallel jobs to {verb} {count} {inputs}".format(
            pool_size=pool_size,
            verb=verb,
            count=len(input_items),
            inputs=pluralize(input_items, noun),
        )
    ):
        with _mp_pool(size=pool_size) as pool:
            for pid, result, elapsed_secs in pool.imap_unordered(apply_function, input_items):
                TRACER.log(
                    "[{pid}] {verbed} {result} in {elapsed_secs:.2f}s".format(
                        pid=pid,
                        verbed=verb_past,
                        result=result_render_function(result) if result_render_function else result,
                        elapsed_secs=elapsed_secs,
                    ),
                    V=2,
                )
                yield result
                slots[pid].append(elapsed_secs)

    TRACER.log(
        "Elapsed time per {verb} job:\n  {times}".format(
            verb=verb,
            times="\n  ".join(
                "{index}) [{pid}] {total_secs:.2f}s {count} {inputs}".format(
                    index=index,
                    pid=pid,
                    count=len(elapsed),
                    inputs=pluralize(elapsed, noun),
                    total_secs=total_secs,
                )
                for index, (total_secs, pid, elapsed) in enumerate(
                    sorted(
                        ((sum(elapsed), pid, elapsed) for pid, elapsed in slots.items()),
                        reverse=True,
                    ),
                    start=1,
                )
            ),
        )
    )


def map_parallel(
    inputs,  # type: Iterable[_I]
    function,  # type: Callable[[_I], _O]
    max_jobs=None,  # type: Optional[int]
    min_average_load=MULTIPROCESSING_DEFAULT_MIN_AVERAGE_LOAD,  # type: int
    costing_function=None,  # type: Optional[Callable[[_I], Comparable]]
    result_render_function=None,  # type: Optional[Callable[[_O], Any]]
    noun="item",  # type: str
    verb="process",  # type: str
    verb_past="processed",  # type: str
):
    # type: (...) -> List[_O]
    """Enhanced version of `multiprocessing.Pool.map` that optimizes pool size and input ordering.

    Unlike `multiprocessing.Pool.map`, the output order is not guaranteed.

    Forwards all arguments to `imap_parallel`.

    :return: A list of the mapped results.
    """
    return list(
        iter_map_parallel(
            inputs,
            function,
            max_jobs=max_jobs,
            min_average_load=min_average_load,
            costing_function=costing_function,
            result_render_function=result_render_function,
            noun=noun,
            verb=verb,
            verb_past=verb_past,
        )
    )
