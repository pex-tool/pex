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


class UnsatisfiableInterpreterConstraintsError(Exception):
  """Indicates interpreter constraints could not be satisfied."""

  def __init__(self, constraints, candidates):
    """
    :param constraints: The constraints that could not be satisfied.
    :type constraints: iterable of str
    :param candidates: The python interpreters that were compared against the constraints.
    :type candidates: iterable of :class:`pex.interpreter.PythonInterpreter`
    """
    self.constraints = tuple(constraints)
    self.candidates = tuple(candidates)
    super(UnsatisfiableInterpreterConstraintsError, self).__init__(self.create_message())

  def create_message(self, preamble=None):
    """Create a message describing  failure to find matching interpreters with an optional preamble.

    :param str preamble: An optional preamble to the message that will be displayed above it
                         separated by an empty blank line.
    :return: A descriptive message useable for display to an end user.
    :rtype: str
    """
    binary_column_width = max(len(candidate.binary) for candidate in self.candidates)
    interpreters_format = '{{binary: >{}}} {{requirement}}'.format(binary_column_width)
    return (
      '{preamble}'
      'Examined the following interpreters:\n  {interpreters}\n\n'
      'None were compatible with the requested constraints:\n  {constraints}'
    ).format(
      preamble='{}\n\n'.format(preamble) if preamble else '',
      interpreters='\n  '.join(interpreters_format.format(
        binary=candidate.binary,
        requirement=candidate.identity.requirement
      ) for candidate in self.candidates),
      constraints='\n  '.join(self.constraints)
    )


def matched_interpreters_iter(interpreters_iter, constraints):
  """Given some filters, yield any interpreter that matches at least one of them.

  :param interpreters_iter: A `PythonInterpreter` iterable for filtering.
  :param constraints: A sequence of strings that constrain the interpreter compatibility for this
    pex. Each string uses the Requirement-style format, e.g. 'CPython>=3' or '>=2.7,<3' for
    requirements agnostic to interpreter class. Multiple requirement strings may be combined
    into a list to OR the constraints, such as ['CPython>=2.7,<3', 'CPython>=3.4'].
  :return: returns a generator that yields compatible interpreters
  :raises: :class:`UnsatisfiableInterpreterConstraintsError` if constraints were given and could
           not be satisfied. The exception will only be raised when the returned generator is fully
           consumed.
  """
  candidates = []
  found = False

  for interpreter in interpreters_iter:
    if any(interpreter.identity.matches(filt) for filt in constraints):
      TRACER.log("Constraints on interpreters: %s, Matching Interpreter: %s"
                 % (constraints, interpreter.binary), V=3)
      found = True
      yield interpreter

    if not found:
      candidates.append(interpreter)

  if not found:
    raise UnsatisfiableInterpreterConstraintsError(constraints, candidates)
