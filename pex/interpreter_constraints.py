# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# A library of functions for filtering Python interpreters based on compatibility constraints

from __future__ import absolute_import

from pex.common import die
from pex.interpreter import PythonIdentity
from pex.tracer import TRACER


def validate_constraints(constraints):
  # TODO: add check to see if constraints are mutually exclusive (bad) so no time is wasted:
  # https://github.com/pantsbuild/pex/issues/432
  for req in constraints:
    # Check that the compatibility requirements are well-formed.
    try:
      PythonIdentity.parse_requirement(req)
    except ValueError as e:
      die("Compatibility requirements are not formatted properly: %s" % str(e))


def matched_interpreters(interpreters, constraints, meet_all_constraints=False):
  """Given some filters, yield any interpreter that matches at least one of them, or all of them
     if meet_all_constraints is set to True.

  :param interpreters: a list of PythonInterpreter objects for filtering
  :param constraints: A sequence of strings that constrain the interpreter compatibility for this
    pex, using the Requirement-style format, e.g. ``'CPython>=3', or just ['>=2.7','<3']``
    for requirements agnostic to interpreter class.
  :param meet_all_constraints: whether to match against all filters.
    Defaults to matching interpreters that match at least one filter.
  :return interpreter: returns a generator that yields compatible interpreters
  """
  check = all if meet_all_constraints else any
  for interpreter in interpreters:
    if check(interpreter.identity.matches(filt) for filt in constraints):
      TRACER.log("Constraints on interpreters: %s, Matching Interpreter: %s"
                 % (constraints, interpreter.binary), V=3)
      yield interpreter
