# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# A library of functions for filtering Python interpreters based on compatibility constraints

def _matches(interpreter, filters, meet_all_constraints=False):
  if meet_all_constraints:
    return all(interpreter.identity.matches(filt) for filt in filters)
  else:
    return any(interpreter.identity.matches(filt) for filt in filters)


def _matching(interpreters, filters, meet_all_constraints=False):
  for interpreter in interpreters:
    if _matches(interpreter, filters, meet_all_constraints):
      yield interpreter


def matched_interpreters(interpreters, filters, meet_all_constraints=False):
  """Given some filters, yield any interpreter that matches at least one of them, or all of them
     if meet_all_constraints is set to True.

  :param interpreters: a list of PythonInterpreter objects for filtering
  :param filters: A sequence of strings that constrain the interpreter compatibility for this
    pex, using the Requirement-style format, e.g. ``'CPython>=3', or just ['>=2.7','<3']``
    for requirements agnostic to interpreter class.
  :param meet_all_constraints: whether to match against all filters.
    Defaults to matching interpreters that match at least one filter.
  """
  for match in _matching(interpreters, filters, meet_all_constraints):
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


def lowest_version_interpreter(interpreters):
  """Given a list of interpreters, return the one with the lowest version."""
  if not interpreters:
    return None
  lowest = interpreters[0]
  for i in interpreters[1:]:
    lowest = lowest if lowest < i else i
  return lowest
