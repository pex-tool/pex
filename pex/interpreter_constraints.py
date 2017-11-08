# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# A library of functions for filtering Python interpreters based on compatibility constraints

from .interpreter import PythonIdentity


def _matches(interpreter, filters, meet_all_constraints=False):
  if meet_all_constraints:
    return all(interpreter.identity.matches(filt) for filt in filters)
  else:
    return any(interpreter.identity.matches(filt) for filt in filters)


def _matching(interpreters, filters, meet_all_constraints=False):
  for interpreter in interpreters:
    if _matches(interpreter, filters, meet_all_constraints):
      yield interpreter


def check_requirements_are_well_formed(constraints):
  # Check that the compatibility requirements are well-formed.
  for req in constraints:
    try:
      PythonIdentity.parse_requirement(req)
    except ValueError as e:
      from .common import die
      die("Compatibility requirements are not formatted properly: %s" % str(e))


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
