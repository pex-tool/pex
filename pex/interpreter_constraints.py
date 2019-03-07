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


def matched_interpreters(interpreters, constraints):
  """Given some filters, yield any interpreter that matches at least one of them.

  :param interpreters: a list of PythonInterpreter objects for filtering
  :param constraints: A sequence of strings that constrain the interpreter compatibility for this
    pex. Each string uses the Requirement-style format, e.g. 'CPython>=3' or '>=2.7,<3' for
    requirements agnostic to interpreter class. Multiple requirement strings may be combined
    into a list to OR the constraints, such as ['CPython>=2.7,<3', 'CPython>=3.4'].
  :return interpreter: returns a generator that yields compatible interpreters
  """
  for interpreter in interpreters:
    if any(interpreter.identity.matches(filt) for filt in constraints):
      TRACER.log("Constraints on interpreters: %s, Matching Interpreter: %s"
                 % (constraints, interpreter.binary), V=3)
      yield interpreter
