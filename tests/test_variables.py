# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pex.variables import Variables


def test_process_pydoc():
  def thing():
    # no pydoc
    pass
  assert Variables.process_pydoc(thing.__doc__) == ('Unknown', 'Unknown')

  def other_thing():
    """Type

    Properly
         formatted
      text.
    """

  assert Variables.process_pydoc(other_thing.__doc__) == (
      'Type', 'Properly formatted text.')


def test_iter_help():
  for variable_name, variable_type, variable_text in Variables.iter_help():
    assert variable_name.startswith('PEX_')
    assert '\n' not in variable_type
    assert '\n' not in variable_text


def test_pex_bool_variables():
  Variables(environ={})._get_bool('NOT_HERE', default=False) is False
  Variables(environ={})._get_bool('NOT_HERE', default=True) is True

  for value in ('0', 'faLsE', 'false'):
    for default in (True, False):
      Variables(environ={'HERE': value})._get_bool('HERE', default=default) is False
  for value in ('1', 'TrUe', 'true'):
    for default in (True, False):
      Variables(environ={'HERE': value})._get_bool('HERE', default=default) is True
  with pytest.raises(SystemExit):
    Variables(environ={'HERE': 'garbage'})._get_bool('HERE')

  # end to end
  assert Variables().PEX_ALWAYS_CACHE is False
  assert Variables({'PEX_ALWAYS_CACHE': '1'}).PEX_ALWAYS_CACHE is True


def test_pex_string_variables():
  Variables(environ={})._get_string('NOT_HERE') is None
  Variables(environ={})._get_string('NOT_HERE', default='lolol') == 'lolol'
  Variables(environ={'HERE': 'stuff'})._get_string('HERE') == 'stuff'
  Variables(environ={'HERE': 'stuff'})._get_string('HERE', default='lolol') == 'stuff'


def test_pex_get_int():
  assert Variables()._get_int('HELLO') is None
  assert Variables()._get_int('HELLO', default=42) == 42
  assert Variables(environ={'HELLO': 23})._get_int('HELLO') == 23
  assert Variables(environ={'HELLO': 23})._get_int('HELLO', default=42) == 23

  with pytest.raises(SystemExit):
    assert Variables(environ={'HELLO': 'welp'})._get_int('HELLO')


def test_pex_vars_set():
  v = Variables(environ={})
  v.set('HELLO', '42')
  assert v._get_int('HELLO') == 42
  v.delete('HELLO')
  assert v._get_int('HELLO') is None
