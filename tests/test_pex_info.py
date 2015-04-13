# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pex.orderedset import OrderedSet
from pex.pex_info import PexInfo


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
