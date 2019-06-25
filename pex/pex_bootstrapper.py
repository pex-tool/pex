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


def _find_pex_python(pex_python):
  def try_create(try_path):
    try:
      return PythonInterpreter.from_binary(try_path)
    except Executor.ExecutionError:
      return None

  interpreter = try_create(pex_python)
  if interpreter:
    # If the target interpreter specified in PEX_PYTHON is an existing absolute path - use it.
    yield interpreter
  else:
    # Otherwise scan the PATH for matches:
    for directory in os.getenv('PATH', '').split(os.pathsep):
      try_path = os.path.join(directory, pex_python)
      interpreter = try_create(try_path)
      if interpreter:
        yield interpreter


def find_compatible_interpreters(path=None, compatibility_constraints=None):
  """Find all compatible interpreters on the system within the supplied constraints and use
     path if it is set. If not, fall back to interpreters on $PATH.
  """
  interpreters = OrderedSet()
  paths = None
  if path:
    paths = path.split(os.pathsep)
  else:
    # We may have been invoked with a specific interpreter, make sure our sys.executable is included
    # as a candidate in this case.
    interpreters.add(PythonInterpreter.get())
  interpreters.update(PythonInterpreter.all(paths=paths))
  return _filter_compatible_interpreters(interpreters,
                                         compatibility_constraints=compatibility_constraints)


def _filter_compatible_interpreters(interpreters, compatibility_constraints=None):
  return list(
    matched_interpreters(interpreters, compatibility_constraints)
    if compatibility_constraints
    else interpreters
  )


def _select_pex_python_interpreter(pex_python, compatibility_constraints=None):
  compatible_interpreters = _filter_compatible_interpreters(
    _find_pex_python(pex_python),
    compatibility_constraints=compatibility_constraints
  )
  if not compatible_interpreters:
    die('Failed to find a compatible PEX_PYTHON={} for constraints: {}'
        .format(pex_python, compatibility_constraints))
  return _select_interpreter(compatible_interpreters)


def _select_path_interpreter(path=None, compatibility_constraints=None):
  compatible_interpreters = find_compatible_interpreters(
    path=path,
    compatibility_constraints=compatibility_constraints
  )
  if not compatible_interpreters:
    die('Failed to find compatible interpreter on path {} for constraints: {}'
        .format(path or os.getenv('PATH'), compatibility_constraints))
  return _select_interpreter(compatible_interpreters)


def _select_interpreter(candidate_interpreters):
  current_interpreter = PythonInterpreter.get()
  if current_interpreter in candidate_interpreters:
    # Always prefer continuing with the current interpreter when possible.
    return current_interpreter
  else:
    # TODO: Allow the selection strategy to be parameterized:
    #   https://github.com/pantsbuild/pex/issues/430
    return min(candidate_interpreters)


def maybe_reexec_pex(compatibility_constraints=None):
  """Handle environment overrides for the Python interpreter to use when executing this pex.

  This function supports interpreter filtering based on interpreter constraints stored in PEX-INFO
  metadata. If PEX_PYTHON is set it attempts to obtain the binary location of the interpreter
  specified by PEX_PYTHON. If PEX_PYTHON_PATH is set, it attempts to search the path for a matching
  interpreter in accordance with the interpreter constraints. If both variables are present, this
  function gives precedence to PEX_PYTHON_PATH and errors out if no compatible interpreters can be
  found on said path.

  If neither variable is set, we fall back to plain PEX execution using PATH searching or the
  currently executing interpreter. If compatibility constraints are used, we match those constraints
  against these interpreters.

  :param compatibility_constraints: optional list of requirements-style strings that constrain the
                                    Python interpreter to re-exec this pex with.
  """

  current_interpreter = PythonInterpreter.get()

  # NB: Used only for tests.
  if '_PEX_EXEC_CHAIN' in os.environ:
    flag_or_chain = os.environ.pop('_PEX_EXEC_CHAIN')
    pex_exec_chain = [] if flag_or_chain == '1' else flag_or_chain.split(os.pathsep)
    pex_exec_chain.append(current_interpreter.binary)
    os.environ['_PEX_EXEC_CHAIN'] = os.pathsep.join(pex_exec_chain)

  current_interpreter_blessed_env_var = '_PEX_SHOULD_EXIT_BOOTSTRAP_REEXEC'
  if os.environ.pop(current_interpreter_blessed_env_var, None):
    # We've already been here and selected an interpreter. Continue to execution.
    return

  with TRACER.timed('Selecting runtime interpreter', V=3):
    if ENV.PEX_PYTHON and not ENV.PEX_PYTHON_PATH:
      # preserve PEX_PYTHON re-exec for backwards compatibility
      # TODO: Kill this off completely in favor of PEX_PYTHON_PATH
      # https://github.com/pantsbuild/pex/issues/431
      TRACER.log('Using PEX_PYTHON={} constrained by {}'
                 .format(ENV.PEX_PYTHON, compatibility_constraints), V=3)
      target = _select_pex_python_interpreter(ENV.PEX_PYTHON,
                                              compatibility_constraints=compatibility_constraints)
    elif ENV.PEX_PYTHON_PATH or compatibility_constraints:
      TRACER.log(
        'Using {path} constrained by {constraints}'.format(
          path='PEX_PYTHON_PATH={}'.format(ENV.PEX_PYTHON_PATH) if ENV.PEX_PYTHON_PATH else '$PATH',
          constraints=compatibility_constraints
        ),
        V=3
      )
      target = _select_path_interpreter(path=ENV.PEX_PYTHON_PATH,
                                        compatibility_constraints=compatibility_constraints)
    else:
      TRACER.log('Using the current interpreter {} since no constraints have been specified.'
                 .format(sys.executable), V=3)
      return

  os.environ.pop('PEX_PYTHON', None)
  os.environ.pop('PEX_PYTHON_PATH', None)

  if target == current_interpreter:
    TRACER.log('Using the current interpreter {} since it matches constraints.'
               .format(sys.executable))
    return

  target_binary = target.binary
  cmdline = [target_binary] + sys.argv
  TRACER.log('Re-executing: cmdline="%s", sys.executable="%s", PEX_PYTHON="%s", '
             'PEX_PYTHON_PATH="%s", COMPATIBILITY_CONSTRAINTS="%s"'
             % (cmdline, sys.executable, ENV.PEX_PYTHON, ENV.PEX_PYTHON_PATH,
                compatibility_constraints))

  # Avoid a re-run through compatibility_constraint checking.
  os.environ[current_interpreter_blessed_env_var] = '1'

  os.execv(target_binary, cmdline)


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
