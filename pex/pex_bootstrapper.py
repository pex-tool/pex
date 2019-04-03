# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
import sys

from pex import pex_warnings
from pex.common import die
from pex.executor import Executor
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import matched_interpreters
from pex.orderedset import OrderedSet
from pex.tracer import TRACER
from pex.variables import ENV

__all__ = ('bootstrap_pex',)


def find_in_path(target_interpreter):
  if os.path.exists(target_interpreter):
    return target_interpreter

  for directory in os.getenv('PATH', '').split(os.pathsep):
    try_path = os.path.join(directory, target_interpreter)
    if os.path.exists(try_path):
      return try_path


def find_compatible_interpreters(pex_python_path=None, compatibility_constraints=None):
  """Find all compatible interpreters on the system within the supplied constraints and use
     PEX_PYTHON_PATH if it is set. If not, fall back to interpreters on $PATH.
  """
  if pex_python_path:
    interpreters = []
    for binary in pex_python_path.split(os.pathsep):
      try:
        interpreters.append(PythonInterpreter.from_binary(binary))
      except Executor.ExecutionError:
        print("Python interpreter %s in PEX_PYTHON_PATH failed to load properly." % binary,
          file=sys.stderr)
    if not interpreters:
      die('PEX_PYTHON_PATH was defined, but no valid interpreters could be identified. Exiting.')
  else:
    # We may have been invoked with a specific interpreter not on the $PATH, make sure our
    # sys.executable is included as a candidate in this case.
    interpreters = OrderedSet([PythonInterpreter.get()])

    # Add all qualifying interpreters found in $PATH.
    interpreters.update(PythonInterpreter.all())

  return list(
    matched_interpreters(interpreters, compatibility_constraints)
    if compatibility_constraints
    else interpreters
  )


def _select_pex_python_interpreter(target_python, compatibility_constraints=None):
  target = find_in_path(target_python)

  if not target:
    die('Failed to find interpreter specified by PEX_PYTHON: %s' % target)
  if compatibility_constraints:
    pi = PythonInterpreter.from_binary(target)
    if not list(matched_interpreters([pi], compatibility_constraints)):
      die('Interpreter specified by PEX_PYTHON (%s) is not compatible with specified '
          'interpreter constraints: %s' % (target, str(compatibility_constraints)))
  if not os.path.exists(target):
    die('Target interpreter specified by PEX_PYTHON %s does not exist. Exiting.' % target)
  return target


def _select_interpreter(pex_python_path=None, compatibility_constraints=None):
  compatible_interpreters = find_compatible_interpreters(
    pex_python_path=pex_python_path, compatibility_constraints=compatibility_constraints)

  if not compatible_interpreters:
    die('Failed to find compatible interpreter for constraints: %s'
        % str(compatibility_constraints))
  # TODO: https://github.com/pantsbuild/pex/issues/430
  target = min(compatible_interpreters).binary

  if os.path.exists(target):
    return target


def maybe_reexec_pex(compatibility_constraints):
  """
  Handle environment overrides for the Python interpreter to use when executing this pex.

  This function supports interpreter filtering based on interpreter constraints stored in PEX-INFO
  metadata. If PEX_PYTHON is set in a pexrc, it attempts to obtain the binary location of the
  interpreter specified by PEX_PYTHON. If PEX_PYTHON_PATH is set, it attempts to search the path for
  a matching interpreter in accordance with the interpreter constraints. If both variables are
  present in a pexrc, this function gives precedence to PEX_PYTHON_PATH and errors out if no
  compatible interpreters can be found on said path.

  If neither variable is set, we fall back to plain PEX execution using PATH searching or the
  currently executing interpreter. If compatibility constraints are used, we match those constraints
  against these interpreters.

  :param compatibility_constraints: list of requirements-style strings that constrain the
  Python interpreter to re-exec this pex with.
  """
  if os.environ.pop('SHOULD_EXIT_BOOTSTRAP_REEXEC', None):
    # We've already been here and selected an interpreter. Continue to execution.
    return

  target = None
  with TRACER.timed('Selecting runtime interpreter based on pexrc', V=3):
    if ENV.PEX_PYTHON and not ENV.PEX_PYTHON_PATH:
      # preserve PEX_PYTHON re-exec for backwards compatibility
      # TODO: Kill this off completely in favor of PEX_PYTHON_PATH
      # https://github.com/pantsbuild/pex/issues/431
      target = _select_pex_python_interpreter(ENV.PEX_PYTHON,
                                              compatibility_constraints=compatibility_constraints)
    elif ENV.PEX_PYTHON_PATH:
      target = _select_interpreter(pex_python_path=ENV.PEX_PYTHON_PATH,
                                   compatibility_constraints=compatibility_constraints)

    elif compatibility_constraints:
      # Apply constraints to target using regular PATH
      target = _select_interpreter(compatibility_constraints=compatibility_constraints)

  if target and os.path.realpath(target) != os.path.realpath(sys.executable):
    cmdline = [target] + sys.argv
    TRACER.log('Re-executing: cmdline="%s", sys.executable="%s", PEX_PYTHON="%s", '
               'PEX_PYTHON_PATH="%s", COMPATIBILITY_CONSTRAINTS="%s"'
               % (cmdline, sys.executable, ENV.PEX_PYTHON, ENV.PEX_PYTHON_PATH,
                  compatibility_constraints))
    ENV.delete('PEX_PYTHON')
    ENV.delete('PEX_PYTHON_PATH')
    os.environ['SHOULD_EXIT_BOOTSTRAP_REEXEC'] = '1'
    os.execve(target, cmdline, ENV.copy())


def _bootstrap(entry_point):
  from .pex_info import PexInfo
  pex_info = PexInfo.from_pex(entry_point)
  pex_warnings.configure_warnings(pex_info)

  from .finders import register_finders
  register_finders()

  return pex_info


def bootstrap_pex(entry_point):
  pex_info = _bootstrap(entry_point)
  maybe_reexec_pex(pex_info.interpreter_constraints)

  from . import pex
  pex.PEX(entry_point).execute()


# NB: This helper is used by third party libs - namely https://github.com/wickman/lambdex.
# TODO(John Sirois): Kill once https://github.com/wickman/lambdex/issues/5 is resolved.
def is_compressed(entry_point):
  from .pex_info import PexInfo
  return os.path.exists(entry_point) and not os.path.exists(os.path.join(entry_point, PexInfo.PATH))


def bootstrap_pex_env(entry_point):
  """Bootstrap the current runtime environment using a given pex."""
  pex_info = _bootstrap(entry_point)

  from .environment import PEXEnvironment
  PEXEnvironment(entry_point, pex_info).activate()
