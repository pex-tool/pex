# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# A library of functions for filtering Python interpreters based on compatibility constraints

def _matches(interpreter, filters, match_all=False):
  if match_all:
    return all(interpreter.identity.matches(filt) for filt in filters)
  else:
    return any(interpreter.identity.matches(filt) for filt in filters)


def _matching(interpreters, filters, match_all=False):
  for interpreter in interpreters:
    if _matches(interpreter, filters, match_all):
      yield interpreter


def matched_interpreters(interpreters, filters, match_all=False):
  """Given some filters, yield any interpreter that matches at least one of them, or all of them
     if match_all is set to True.

  :param interpreters: a list of PythonInterpreter objects for filtering
  :param filters: A sequence of strings that constrain the interpreter compatibility for this
    pex, using the Requirement-style format, e.g. ``'CPython>=3', or just ['>=2.7','<3']``
    for requirements agnostic to interpreter class.
  :param match_all: whether to match against all constraints. Defaults to matching one constraint.
  """
  for match in _matching(interpreters, filters, match_all):
    yield match


def parse_interpreter_constraints(constraints_string):
  """Given a single string defining interpreter constraints, separate them into a list of
    individual constraint items for PythonIdentity to consume.

    Example: '>=2.7, <3'
    Return: ['>=2.7', '<3']

    Example: 'CPython>=2.7,<3'
    Return: ['CPython>=2.7', 'CPython<3']
  """
  if 'CPython' in constraints_string:
    return list(map(lambda x: 'CPython' + x.strip() if not 'CPython' in x else x.strip(),
      constraints_string.split(',')))
  else:
    return list(map(lambda x: x.strip(), constraints_string.split(',')))
