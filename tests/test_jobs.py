# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import subprocess
from textwrap import dedent

import pytest

from pex.interpreter import spawn_python_job
from pex.jobs import _ABSOLUTE_MAX_JOBS, DEFAULT_MAX_JOBS, Job, SpawnedJob, _sanitize_max_jobs
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Dict


def test_sanitize_max_jobs_none():
    # type: () -> None
    assert DEFAULT_MAX_JOBS == _sanitize_max_jobs(None)


def test_sanitize_max_jobs_less_then_one():
    # type: () -> None
    assert DEFAULT_MAX_JOBS == _sanitize_max_jobs(0)
    assert DEFAULT_MAX_JOBS == _sanitize_max_jobs(-1)
    assert DEFAULT_MAX_JOBS == _sanitize_max_jobs(-5)


def test_sanitize_max_jobs_nominal():
    # type: () -> None
    assert 1 == _sanitize_max_jobs(1)


def test_sanitize_max_jobs_too_large():
    # type: () -> None
    assert _ABSOLUTE_MAX_JOBS == _sanitize_max_jobs(_ABSOLUTE_MAX_JOBS)
    assert _ABSOLUTE_MAX_JOBS == _sanitize_max_jobs(_ABSOLUTE_MAX_JOBS + 1)
    assert _ABSOLUTE_MAX_JOBS == _sanitize_max_jobs(_ABSOLUTE_MAX_JOBS + 5)


def create_error_job(exit_code):
    # type: (int) -> Job
    return spawn_python_job(args=["-c", "import sys; sys.exit({})".format(exit_code)])


def test_spawn_wait():
    # type: () -> None
    result = object()
    assert (
        result is SpawnedJob.wait(job=spawn_python_job(args=["-V"]), result=result).await_result()
    )

    spawned_job = SpawnedJob.wait(job=create_error_job(42), result=1 / 137)
    with pytest.raises(Job.Error) as exec_info:
        spawned_job.await_result()
    assert 42 == exec_info.value.exitcode


def test_spawn_and_then(tmpdir):
    # type: (Any) -> None
    side_effect_file = os.path.join(str(tmpdir), "side.effect")

    def observe_side_effect():
        # type: () -> Dict[str, int]
        with open(side_effect_file) as fp:
            return cast("Dict[str, int]", json.load(fp))

    assert (
        {"exit_code": 42}
        == SpawnedJob.and_then(
            job=spawn_python_job(
                args=[
                    "-c",
                    dedent(
                        """\
                    import json

                    with open({side_effect_file!r}, "w") as fp:
                        json.dump({{"exit_code": 42}}, fp)
                    """
                    ).format(side_effect_file=side_effect_file),
                ]
            ),
            result_func=observe_side_effect,
        ).await_result()
    )

    spawned_job = SpawnedJob.and_then(job=create_error_job(3), result_func=lambda: 1 / 137)
    with pytest.raises(Job.Error) as exec_info:
        spawned_job.await_result()
    assert 3 == exec_info.value.exitcode


def test_spawn_stdout():
    # type: () -> None
    assert (
        "Jane\n"
        == SpawnedJob.stdout(
            job=spawn_python_job(
                args=["-c", "import sys; print(sys.stdin.read())"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            ),
            result_func=lambda stdout: stdout.decode("utf-8"),
            input=b"Jane",
        ).await_result()
    )

    spawned_job = SpawnedJob.stdout(create_error_job(137), lambda output: 42)
    with pytest.raises(Job.Error) as exec_info:
        spawned_job.await_result()
    assert 137 == exec_info.value.exitcode
