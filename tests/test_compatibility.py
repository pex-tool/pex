# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pex.compatibility import to_bytes


def test_to_bytes():
  assert isinstance(to_bytes(''), bytes)
  assert isinstance(to_bytes('abc'), bytes)
  assert isinstance(to_bytes(b'abc'), bytes)
  assert isinstance(to_bytes(u'abc'), bytes)
  assert isinstance(to_bytes(b'abc'.decode('latin-1'), encoding='utf-8'), bytes)

  for bad_values in (123, None):
    with pytest.raises(ValueError):
      to_bytes(bad_values)
