# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.jobs import _ABSOLUTE_MAX_JOBS, DEFAULT_MAX_JOBS, _sanitize_max_jobs


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
