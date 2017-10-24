# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pex.interpreter_constraints import parse_interpreter_constraints


def test_parse_interpreter_constraints():
  example_input = '>=2.7, <3'
  assert parse_interpreter_constraints(example_input) == ['>=2.7', '<3']

  example_input = '>=2.7,<3'
  assert parse_interpreter_constraints(example_input) == ['>=2.7', '<3']

  example_input = 'CPython>=2.7,<3'
  assert parse_interpreter_constraints(example_input) == ['CPython>=2.7', 'CPython<3']

  example_input = 'CPython>=2.7, <3'
  assert parse_interpreter_constraints(example_input) == ['CPython>=2.7', 'CPython<3']

  example_input = 'CPython==3.6'
  assert parse_interpreter_constraints(example_input) == ['CPython==3.6']

  with pytest.raises(SystemExit) as e:
    example_input = 'CPython>=?.2.7,=<3>'
    parse_interpreter_constraints(example_input)
    assert 'Unknown requirement string' in str(e.info)

    example_input = '==2,2.7><,3_9'
    parse_interpreter_constraints(example_input)
    assert 'Unknown requirement string' in str(e.info)
