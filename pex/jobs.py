# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import errno
from threading import BoundedSemaphore, Event, Thread

from pex.compatibility import Queue, cpu_count
from pex.tracer import TRACER


class Job(object):
  """Represents a job spawned as a subprocess.

  Presents a similar API to `subprocess` except where noted.
  """

  class Error(Exception):
    """Indicates that a Job exited non-zero."""

  def __init__(self, command, process):
    """
    :param command: The command used to spawn the job process.
    :type command: list of str
    :param process: The spawned process handle.
    :type process: :class:`subprocess.Popen`
    """
    self._command = command
    self._process = process

  def wait(self):
    """Waits for the job to complete.

    :raises: :class:`Job.Error` if the job exited non-zero.
    """
    self._process.wait()
    self._check_returncode()

  def communicate(self, input=None):
    """Communicates with the job sending any input data to stdin and collecting stdout and stderr.

    :param input: Data to send to stdin of the job as per the `subprocess` API.
    :return: A tuple of the job's stdout and stderr as per the `subprocess` API.
    :raises: :class:`Job.Error` if the job exited non-zero.
    """
    stdout, stderr = self._process.communicate(input=input)
    self._check_returncode(stderr)
    return stdout, stderr

  def kill(self):
    """Terminates the job if it is still running.

    N.B.: This method is idempotent.
    """
    try:
      self._process.kill()
    except OSError as e:
      if e.errno != errno.ESRCH:
        raise e

  def _check_returncode(self, stderr=None):
    if self._process.returncode != 0:
      msg = 'Executing {} failed with {}'.format(' '.join(self._command), self._process.returncode)
      if stderr:
        msg += '\nSTDERR:\n{}'.format(stderr.decode('utf-8'))
      raise self.Error(msg)

  def __str__(self):
    return 'pid: {pid} -> {command}'.format(pid=self._process.pid, command=' '.join(self._command))


class SpawnedJob(object):
  """A handle to a spawned :class:`Job` and its associated result."""

  @classmethod
  def completed(cls, result):
    """Wrap an already completed result in a SpawnedJob.

    The returned job will no-op when `kill` is called since the job is already completed.

    :param result: The completed result.
    :return: A spawned job whose result is already complete.
    :rtype: :class:`SpawnedJob`
    """
    class Completed(SpawnedJob):
      def __init__(self):
        super(Completed, self).__init__(job=None, result_func=lambda: result)

      def kill(self):
        pass

      def __str__(self):
        return 'SpawnedJob.completed({})'.format(result)

    return Completed()

  @classmethod
  def wait(cls, job, result):
    """Wait for the job to complete and return a fixed result upon success.

    :param job: The spawned job.
    :type job: :class:`Job`
    :param result: The fixed success result.
    :return: A spawned job whose result is a side effect of the job (a written file, a populated
             directory, etc.).
    :rtype: :class:`SpawnedJob`
    """
    def wait_result_func():
      job.wait()
      return result

    return cls(job=job, result_func=wait_result_func)

  @classmethod
  def stdout(cls, job, result_func, input=None):
    """Wait for the job to complete and return a result derived from its stdout.

    :param job: The spawned job.
    :type job: :class:`Job`
    :param result_func: A function taking the stdout byte string collected from the spawned job and
                        returning the desired result.
    :param input: Optional input stream data to pass to the process as per the
                  `subprocess.Popen.communicate` API.
    :return: A spawned job whose result is derived from stdout contents.
    :rtype: :class:`SpawnedJob`
    """
    def stdout_result_func():
      stdout, _ = job.communicate(input=input)
      return result_func(stdout)

    return cls(job=job, result_func=stdout_result_func)

  def __init__(self, job, result_func):
    """Not intended for direct use, see `wait` and `stdout` factories."""
    self._job = job
    self._result_func = result_func

  def await_result(self):
    """Waits for the spawned job to complete and returns its result."""
    return self._result_func()

  def kill(self):
    """Terminates the spawned job if it's not already complete."""
    self._job.kill()

  def __str__(self):
    return str(self._job)


_CPU_COUNT = cpu_count()
_ABSOLUTE_MAX_JOBS = _CPU_COUNT * 2


DEFAULT_MAX_JOBS = _CPU_COUNT
"""The default maximum number of parallel jobs PEX should use."""


def _sanitize_max_jobs(max_jobs=None):
  assert max_jobs is None or isinstance(max_jobs, int)
  if max_jobs is None or max_jobs <= 0:
    return DEFAULT_MAX_JOBS
  else:
    return min(max_jobs, _ABSOLUTE_MAX_JOBS)


def execute_parallel(inputs, spawn_func, raise_type=None, max_jobs=None):
  """Execute jobs for the given inputs in parallel.

  :param int max_jobs: The maximum number of parallel jobs to spawn.
  :param inputs: An iterable of the data to parallelize over `spawn_func`.
  :param spawn_func: A function taking a single input and returning a :class:`SpawnedJob`.
  :param raise_type: An optional type that takes a single string argument and will be used to
                     construct a raiseable value when any of the spawned jobs errors. `None` by
                     default which indicates spawned jobs that error should be skipped; i.e.: the
                     returned iterator over spawned job results will return less results than
                     inputs.
  :returns: An iterator over the spawned job results as they come in.
  :raises: A `raise_type` exception if any individual job errors and `raise_type` is not `None`.
  """
  size = _sanitize_max_jobs(max_jobs)
  TRACER.log('Spawning a maximum of {} parallel jobs to process:\n  {}'
             .format(size, '\n  '.join(map(str, inputs))),
             V=9)

  class SpawnError(Exception):
    def __init__(self, item, error):
      self.item = item
      self.error = error

  stop = Event()  # Used as a signal to stop spawning further jobs once any one job fails.
  job_slots = BoundedSemaphore(value=size)
  done_sentinel = object()
  spawned_job_queue = Queue()  # Queue[Union[SpawnedJob, SpawnError, Literal[done_sentinel]]]

  def spawn_jobs():
    for item in inputs:
      if stop.is_set():
        break
      job_slots.acquire()
      try:
        result = spawn_func(item)
      except Exception as e:
        result = SpawnError(item, e)
      finally:
        spawned_job_queue.put(result)
    spawned_job_queue.put(done_sentinel)

  spawner = Thread(name='PEX Parallel Job Spawner', target=spawn_jobs)
  spawner.daemon = True
  spawner.start()

  error = None
  while True:
    item = spawned_job_queue.get()

    if item is done_sentinel:
      if error:
        raise error
      return

    try:
      if isinstance(item, SpawnError):
        if raise_type:
          error = item.error
        else:
          # Otherwise, if we were given no `raise_type`, we skip over the input that raised.
          TRACER.log('Failed to spawn a job for {}: {} raised {}'
                     .format(item.item, spawn_func, item.error))
      elif error is not None:  # I.E.: `item` is not an exception, but there was a prior exception.
        item.kill()
      else:
        try:
          yield item.await_result()
        except Job.Error as e:
          if raise_type:
            # Fail fast and proceed to kill all outstanding spawned jobs.
            stop.set()
            error = raise_type('{} raised {}'.format(item, e))
          else:
            # Otherwise, if we were given no `raise_type`, we continue on and just log the failure.
            TRACER.log('{} raised {}'.format(item, e))
    finally:
      job_slots.release()
