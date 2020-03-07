# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# A library of functions for filtering Python interpreters based on compatibility constraints

from __future__ import absolute_import

from pex.common import die
from pex.interpreter import PythonIdentity
from pex.third_party import boolean
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


def matched_interpreters_iter(interpreters_iter, constraints):
  """Given some filters, yield any interpreter that matches at least one of them.

  :param interpreters_iter: A `PythonInterpreter` iterable for filtering.
  :param constraints: A sequence of strings that constrain the interpreter compatibility for this
    pex. Eeach string is an arbitrary boolean expression in which the atoms are Requirement-style
    strings such as 'CPython>=3', or '>=2.7,<3' for requirements agnostic to interpreter class.
    The infix boolean operators are |, & and ~, and parentheses are used for precedence.
    Multiple requirement strings are OR-ed, e.g., ['CPython>=2.7,<3', 'CPython>=3.4'], is the same
    as ['CPython>=2.7,<3 | CPython>=3.4'].
  :return interpreter: returns a generator that yields compatible interpreters
  """
  # TODO: Deprecate specifying multiple constraints, and instead require the input to be a
  #  single explicit boolean expression.
  constraint_expr = '({})'.format(' | '.join(constraints))
  for interpreter in interpreters_iter:
    if match_interpreter_constraint(interpreter.identity, constraint_expr):
      TRACER.log("Constraints on interpreters: %s, Matching Interpreter: %s"
                 % (constraints, interpreter.binary), V=3)
      yield interpreter


class ConstraintAlgebra(boolean.BooleanAlgebra):
  def __init__(self, identity):
    super(ConstraintAlgebra, self).__init__()
    self._identity = identity

  def tokenize(self, s):
    # Remove all spaces from the string. Doesn't change its semantics, but makes it much
    # easier to tokenize.
    s = ''.join(s.split())
    if not s:
      return
    ops = {
      '|': boolean.TOKEN_OR,
      '&': boolean.TOKEN_AND,
      '~': boolean.TOKEN_NOT,
      '(': boolean.TOKEN_LPAR,
      ')': boolean.TOKEN_RPAR,
    }
    s = '({})'.format(s)  # Wrap with parens, to simplify constraint tokenizing.
    it = enumerate(s)
    try:
      i, c = next(it)
      while True:
        if c in ops:
          yield ops[c], c, i
          i, c = next(it)
        else:
          constraint_start = i
          while not c in ops:
            i, c = next(it)  # We wrapped with parens, so this cannot throw StopIteration.
          constraint = s[constraint_start:i]
          yield ((boolean.TOKEN_TRUE if self._identity.matches(constraint)
                  else boolean.TOKEN_FALSE),
                 constraint, constraint_start)
    except StopIteration:
      pass


def match_interpreter_constraint(identity, constraint_expr):
  """Return True iff the given identity matches the constraint expression.

  The constraint expression is an arbitrary boolean expression in which the atoms are
  Requirement-style strings such as 'CPython>=2.7,<3', the infix boolean operators are |, & and ~,
  and parentheses are used for precedence.

  :param identity: A `pex.interpreter.PythonIdentity` instance.
  :param constraint_expr: A boolean interpreter constraint expression.
  """
  algebra = ConstraintAlgebra(identity)
  return bool(algebra.parse(constraint_expr).simplify())
