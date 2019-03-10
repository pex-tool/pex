# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import warnings

import pytest

from pex import pex_warnings
from pex.compatibility import PY2
from pex.pex_info import PexInfo
from pex.pex_warnings import PEXWarning
from pex.variables import Variables


def exercise_warnings(pex_info, **env):
  with warnings.catch_warnings(record=True) as events:
    pex_warnings.configure_warnings(pex_info, env=Variables(environ=env))
    pex_warnings.warn('test')
    return events


def assert_warnings(pex_info, **env):
  events = exercise_warnings(pex_info, **env)
  assert 1 == len(events)
  warning = events[0]
  assert PEXWarning == warning.category
  assert 'test' == str(warning.message)


def assert_no_warnings(pex_info, **env):
  events = exercise_warnings(pex_info, **env)
  assert 0 == len(events)


def pex_info_no_emit_warnings():
  pex_info = PexInfo.default()
  pex_info.emit_warnings = False
  return pex_info


skip_py2_warnings = pytest.mark.skipif(
  PY2,
  reason="The `warnings.catch_warnings` mechanism doesn't work properly under CPython 2.7 & pypy "
         "across multiple tests. Since we only use `warnings.catch_warnings` in unit tests and "
         "the mechanisms tested here are also tested in integration tests under CPython 2.7 & pypy "
         "we accept that these unit tests appear un-fixable without alot of warnings mocking.")


@skip_py2_warnings
def test_emit_warnings_default_on():
  assert_warnings(PexInfo.default())


@skip_py2_warnings
def test_emit_warnings_pex_info_off():
  assert_no_warnings(pex_info_no_emit_warnings())


@skip_py2_warnings
def test_emit_warnings_emit_env_off():
  assert_no_warnings(PexInfo.default(), PEX_EMIT_WARNINGS='0')


@skip_py2_warnings
def test_emit_warnings_pex_info_off_emit_env_override():
  assert_warnings(pex_info_no_emit_warnings(), PEX_EMIT_WARNINGS='1')


@skip_py2_warnings
def test_emit_warnings_pex_info_off_verbose_override():
  assert_warnings(pex_info_no_emit_warnings(), PEX_VERBOSE='1')


@skip_py2_warnings
def test_emit_warnings_pex_info_off_verbose_trumps_emit_env():
  assert_warnings(pex_info_no_emit_warnings(), PEX_VERBOSE='1', PEX_EMIT_WARNINGS='0')
