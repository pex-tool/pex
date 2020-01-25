# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.interpreter import PythonInterpreter
from pex.platforms import Platform


class DistributionTarget(object):
  """Represents the target of a python distribution."""

  @classmethod
  def current(cls):
    return cls(interpreter=None, platform=None)

  @classmethod
  def for_interpreter(cls, interpreter):
    return cls(interpreter=interpreter, platform=None)

  @classmethod
  def for_platform(cls, platform):
    return cls(interpreter=None, platform=platform)

  def __init__(self, interpreter=None, platform=None):
    self._interpreter = interpreter
    self._platform = platform

  @property
  def is_foreign(self):
    if self._platform is None:
      return False
    return self._platform != Platform.of_interpreter(self._interpreter)

  def get_interpreter(self):
    return self._interpreter or PythonInterpreter.get()

  def get_platform(self):
    return self._platform or Platform.current()

  def requirement_applies(self, requirement):
    """Determines if the given requirement applies to this distribution target.

    :param requirement: The requirement to evaluate.
    :type requirement: :class:`pex.third_party.pkg_resources.Requirement`
    :rtype: bool
    """
    if not requirement.marker:
      return True

    if self._interpreter is None:
      return True

    return requirement.marker.evaluate(self._interpreter.identity.env_markers)

  @property
  def id(self):
    """A unique id for a resolve target suitable as a path name component.

    :rtype: str
    """
    if self._platform is None:
      interpreter = self.get_interpreter()
      return '{python}-{abi}'.format(python=interpreter.identity.python_tag,
                                     abi=interpreter.identity.abi_tag)
    else:
      return str(self._platform)

  def __repr__(self):
    if self._platform is None:
      return 'Target(interpreter={!r})'.format(self.get_interpreter())
    else:
      return 'Target(platform={!r})'.format(self._platform)

  def _tup(self):
    return self._interpreter, self._platform

  def __eq__(self, other):
    if type(other) is not type(self):
      return NotImplemented
    return self._tup() == other._tup()

  def __hash__(self):
    return hash(self._tup())
