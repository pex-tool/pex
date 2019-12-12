# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
import sys

from pex import pex_warnings
from pex.common import die
from pex.executor import Executor
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import matched_interpreters_iter
from pex.orderedset import OrderedSet
from pex.tracer import TRACER
from pex.variables import ENV

__all__ = ('bootstrap_pex',)


def _iter_pex_python(pex_python):
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
    try_paths = OrderedSet(os.path.realpath(os.path.join(directory, pex_python))
                           for directory in os.getenv('PATH', '').split(os.pathsep))

    # Prefer the current interpreter if present in the `path`.
    current_interpreter = PythonInterpreter.get()
    if current_interpreter.binary in try_paths:
      try_paths.remove(current_interpreter.binary)
      yield current_interpreter

    for try_path in try_paths:
      interpreter = try_create(try_path)
      if interpreter:
        yield interpreter


def iter_compatible_interpreters(path=None, compatibility_constraints=None):
  """Find all compatible interpreters on the system within the supplied constraints and use
     path if it is set. If not, fall back to interpreters on $PATH.
  """
  def _iter_interpreters():
    seen = set()

    paths = None
    current_interpreter = PythonInterpreter.get()
    if path:
      paths = OrderedSet(os.path.realpath(p) for p in path.split(os.pathsep))

      # Prefer the current interpreter if present on the `path`.
      candidate_paths = frozenset((current_interpreter.binary,
                                   os.path.dirname(current_interpreter.binary)))
      candidate_paths_in_path = candidate_paths.intersection(paths)
      if candidate_paths_in_path:
        for p in candidate_paths_in_path:
          paths.remove(p)
        seen.add(current_interpreter)
        yield current_interpreter
    else:
      # We may have been invoked with a specific interpreter, make sure our sys.executable is
      # included as a candidate in this case.
      seen.add(current_interpreter)
      yield current_interpreter

    for interp in PythonInterpreter.iter(paths=paths):
      if interp not in seen:
        seen.add(interp)
        yield interp

  return _compatible_interpreters_iter(_iter_interpreters(),
                                       compatibility_constraints=compatibility_constraints)


def _compatible_interpreters_iter(interpreters_iter, compatibility_constraints=None):
  if compatibility_constraints:
    for interpreter in matched_interpreters_iter(interpreters_iter, compatibility_constraints):
      yield interpreter
  else:
    for interpreter in interpreters_iter:
      yield interpreter


def _select_pex_python_interpreter(pex_python, compatibility_constraints=None):
  compatible_interpreters_iter = _compatible_interpreters_iter(
    _iter_pex_python(pex_python),
    compatibility_constraints=compatibility_constraints
  )
  selected = _select_interpreter(compatible_interpreters_iter)
  if not selected:
    die('Failed to find a compatible PEX_PYTHON={} for constraints: {}'
        .format(pex_python, compatibility_constraints))
  return selected


def _select_path_interpreter(path=None, compatibility_constraints=None):
  compatible_interpreters_iter = iter_compatible_interpreters(
    path=path,
    compatibility_constraints=compatibility_constraints
  )
  selected = _select_interpreter(compatible_interpreters_iter)
  if not selected:
    die('Failed to find compatible interpreter on path {} for constraints: {}'
        .format(path or os.getenv('PATH'), compatibility_constraints))
  return selected


def _select_interpreter(candidate_interpreters_iter):
  current_interpreter = PythonInterpreter.get()
  candidate_interpreters = []
  for interpreter in candidate_interpreters_iter:
    if current_interpreter == interpreter:
      # Always prefer continuing with the current interpreter when possible.
      return current_interpreter
    else:
      candidate_interpreters.append(interpreter)
  if not candidate_interpreters:
    return None

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

  from . import pex
  pythonpath = pex.PEX.stash_pythonpath()
  if pythonpath is not None:
    TRACER.log('Stashed PYTHONPATH of {}'.format(pythonpath), V=2)

  with TRACER.timed('Selecting runtime interpreter', V=3):
    if ENV.PEX_PYTHON and not ENV.PEX_PYTHON_PATH:
      # preserve PEX_PYTHON re-exec for backwards compatibility
      # TODO: Kill this off completely in favor of PEX_PYTHON_PATH
      # https://github.com/pantsbuild/pex/issues/431
      TRACER.log('Using PEX_PYTHON={} constrained by {}'
                 .format(ENV.PEX_PYTHON, compatibility_constraints), V=3)
      target = _select_pex_python_interpreter(pex_python=ENV.PEX_PYTHON,
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
    elif pythonpath is None:
      TRACER.log('Using the current interpreter {} since no constraints have been specified and '
                 'PYTHONPATH is not set.'.format(sys.executable), V=3)
      return
    else:
      target = current_interpreter

  os.environ.pop('PEX_PYTHON', None)
  os.environ.pop('PEX_PYTHON_PATH', None)

  if pythonpath is None and target == current_interpreter:
    TRACER.log('Using the current interpreter {} since it matches constraints and '
               'PYTHONPATH is not set.'.format(sys.executable))
    return

  target_binary = target.binary
  cmdline = [target_binary] + sys.argv
  TRACER.log(
    'Re-executing: '
    'cmdline={cmdline!r}, '
    'sys.executable={python!r}, '
    'PEX_PYTHON={pex_python!r}, '
    'PEX_PYTHON_PATH={pex_python_path!r}, '
    'COMPATIBILITY_CONSTRAINTS={compatibility_constraints!r}'
    '{pythonpath}"'.format(
      cmdline=' '.join(cmdline),
      python=sys.executable,
      pex_python=ENV.PEX_PYTHON,
      pex_python_path=ENV.PEX_PYTHON_PATH,
      compatibility_constraints=compatibility_constraints,
      pythonpath=', (stashed) PYTHONPATH="{}"'.format(pythonpath) if pythonpath is not None else '')
  )

  # Avoid a re-run through compatibility_constraint checking.
  os.environ[current_interpreter_blessed_env_var] = '1'

  os.execv(target_binary, cmdline)


def _bootstrap(entry_point):
  from .pex_info import PexInfo
  pex_info = PexInfo.from_pex(entry_point)
  pex_warnings.configure_warnings(pex_info)
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
