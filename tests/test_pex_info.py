# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path

import pytest

from pex.bin.pex import make_relative_to_root
from pex.orderedset import OrderedSet
from pex.pex_info import PexInfo
from pex.variables import ENV, Variables


def make_pex_info(requirements):
  return PexInfo(info={'requirements': requirements})


def test_backwards_incompatible_pex_info():
  # forwards compatibility
  pi = make_pex_info(['hello'])
  assert pi.requirements == OrderedSet(['hello'])

  pi = make_pex_info(['hello==0.1', 'world==0.2'])
  assert pi.requirements == OrderedSet(['hello==0.1', 'world==0.2'])

  # malformed
  with pytest.raises(ValueError):
    make_pex_info('hello')

  with pytest.raises(ValueError):
    make_pex_info([('hello', False)])

  # backwards compatibility
  pi = make_pex_info([
      ['hello==0.1', False, None],
      ['world==0.2', False, None],
  ])
  assert pi.requirements == OrderedSet(['hello==0.1', 'world==0.2'])


def assert_same_info(expected, actual):
  assert expected.dump(sort_keys=True) == actual.dump(sort_keys=True)


def test_from_empty_env():
  environ = Variables(environ={})
  info = {}
  assert_same_info(PexInfo(info=info), PexInfo.from_env(env=environ))


def test_make_relative():
  with ENV.patch(PEX_ROOT='/pex_root'):
    assert '/pex_root/interpreters' == make_relative_to_root('{pex_root}/interpreters')

    #Verify the user can specify arbitrary absolute paths.
    assert '/tmp/interpreters' == make_relative_to_root('/tmp/interpreters')


def test_from_env():
  pex_root = os.path.realpath('/pex_root')
  environ = dict(PEX_ROOT=pex_root,
                 PEX_MODULE='entry:point',
                 PEX_SCRIPT='script.sh',
                 PEX_FORCE_LOCAL='true',
                 PEX_INHERIT_PATH='true',
                 PEX_IGNORE_ERRORS='true',
                 PEX_ALWAYS_CACHE='true')

  info = dict(pex_root=pex_root,
              entry_point='entry:point',
              script='script.sh',
              zip_safe=False,
              inherit_path=True,
              ignore_errors=True,
              always_write_cache=True)

  assert_same_info(PexInfo(info=info), PexInfo.from_env(env=Variables(environ=environ)))
