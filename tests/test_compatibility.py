# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pex.compatibility import to_bytes, to_unicode, unicode_string


def test_to_bytes():
  assert isinstance(to_bytes(''), bytes)
  assert isinstance(to_bytes('abc'), bytes)
  assert isinstance(to_bytes(b'abc'), bytes)
  assert isinstance(to_bytes(u'abc'), bytes)
  assert isinstance(to_bytes(b'abc'.decode('latin-1'), encoding='utf-8'), bytes)

  for bad_value in (123, None):
    with pytest.raises(ValueError):
      to_bytes(bad_value)


def test_to_unicode():
  assert isinstance(to_unicode(''), unicode_string)
  assert isinstance(to_unicode('abc'), unicode_string)
  assert isinstance(to_unicode(b'abc'), unicode_string)
  assert isinstance(to_unicode(u'abc'), unicode_string)
  assert isinstance(to_unicode(u'abc'.encode('latin-1'), encoding='latin-1'), unicode_string)

  for bad_value in (123, None):
    with pytest.raises(ValueError):
      to_unicode(bad_value)
