# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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
