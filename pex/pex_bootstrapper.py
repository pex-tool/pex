# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys

from .common import die, open_zip
from .executor import Executor
from .interpreter import PythonInterpreter
from .interpreter_constraints import matched_interpreters
from .tracer import TRACER
from .variables import ENV

__all__ = ('bootstrap_pex',)


def pex_info_name(entry_point):
  """Return the PEX-INFO for an entry_point"""
  return os.path.join(entry_point, 'PEX-INFO')


def is_compressed(entry_point):
  return os.path.exists(entry_point) and not os.path.exists(pex_info_name(entry_point))


def read_pexinfo_from_directory(entry_point):
  with open(pex_info_name(entry_point), 'rb') as fp:
    return fp.read()


def read_pexinfo_from_zip(entry_point):
  with open_zip(entry_point) as zf:
    return zf.read('PEX-INFO')


def read_pex_info_content(entry_point):
  """Return the raw content of a PEX-INFO."""
  if is_compressed(entry_point):
    return read_pexinfo_from_zip(entry_point)
  else:
    return read_pexinfo_from_directory(entry_point)


def get_pex_info(entry_point):
  """Return the PexInfo object for an entry point."""
  from . import pex_info

  pex_info_content = read_pex_info_content(entry_point)
  if pex_info_content:
    return pex_info.PexInfo.from_json(pex_info_content)
  raise ValueError('Invalid entry_point: %s' % entry_point)


def find_in_path(target_interpreter):
  if os.path.exists(target_interpreter):
    return target_interpreter

  for directory in os.getenv('PATH', '').split(os.pathsep):
    try_path = os.path.join(directory, target_interpreter)
    if os.path.exists(try_path):
      return try_path


def _get_python_interpreter(binary):
  try:
    return PythonInterpreter.from_binary(binary)
  # from_binary attempts to execute the interpreter
  except Executor.ExecutionError:
    return None


def _find_compatible_interpreters(pex_python_path, compatibility_constraints):
  """Find all compatible interpreters on the system within the supplied constraints and use
     PEX_PYTHON_PATH env variable if it is set. If not, fall back to interpreters on $PATH.
  """
  if pex_python_path:
    interpreters = []
    for binary in pex_python_path.split(os.pathsep):
      pi = _get_python_interpreter(binary)
      if pi:
        interpreters.append(pi)
    if not interpreters:
      die('No interpreters from PEX_PYTHON_PATH can be found on the system. Exiting.')
  else:
    # All qualifying interpreters found in $PATH
    interpreters = PythonInterpreter.all()

  compatible_interpreters = list(matched_interpreters(
    interpreters, compatibility_constraints, meet_all_constraints=True))
  return compatible_interpreters if compatible_interpreters else None


def _handle_pex_python(target_python, compatibility_constraints):
  """Re-exec using the PEX_PYTHON interpreter"""
  target = find_in_path(target_python)
  if not target:
    die('Failed to find interpreter specified by PEX_PYTHON: %s' % target)
  elif compatibility_constraints:
    pi = PythonInterpreter.from_binary(target)
    if not all(pi.identity.matches(constraint) for constraint in compatibility_constraints):
      die('Interpreter specified by PEX_PYTHON (%s) is not compatible with specified '
          'interpreter constraints: %s' % (target, str(compatibility_constraints)))
  if os.path.exists(target) and os.path.realpath(target) != os.path.realpath(sys.executable):
    TRACER.log('Detected PEX_PYTHON, re-exec to %s' % target)
    ENV.SHOULD_EXIT_BOOTSTRAP_REEXEC = True
    os.execve(target, [target_python] + sys.argv, ENV.copy())


def _handle_general_interpreter_selection(pex_python_path, compatibility_constraints):
  """Handle selection in the case that PEX_PYTHON_PATH is set or interpreter compatibility
     constraints are specified.
  """
  compatible_interpreters = _find_compatible_interpreters(
    pex_python_path, compatibility_constraints)

  target = None
  if compatible_interpreters:
    target = min(compatible_interpreters).binary
  if not target:
    die('Failed to find compatible interpreter for constraints: %s'
        % str(compatibility_constraints))
  if os.path.exists(target) and os.path.realpath(target) != os.path.realpath(sys.executable):
    if pex_python_path:
      TRACER.log('Detected PEX_PYTHON_PATH, re-exec to %s' % target)
    else:
      TRACER.log('Re-exec to interpreter %s that matches constraints: %s' % (target,
        str(compatibility_constraints)))
    ENV.SHOULD_EXIT_BOOTSTRAP_REEXEC = True
    os.execve(target, [target] + sys.argv, ENV.copy())


def maybe_reexec_pex(compatibility_constraints=None):
  if ENV.SHOULD_EXIT_BOOTSTRAP_REEXEC:
    return
  if ENV.PEX_PYTHON and ENV.PEX_PYTHON_PATH:
    # both vars are defined, fall through to PEX_PYTHON_PATH resolution (give precedence to PPP)
    pass
  elif ENV.PEX_PYTHON:
    # preserve PEX_PYTHON re-exec for backwards compatibility
    _handle_pex_python(ENV.PEX_PYTHON, compatibility_constraints)

  if not compatibility_constraints:
    # if no compatibility constraints are specified, we want to match against
    # the lowest-versioned interpreter in PEX_PYTHON_PATH if it is set
    if not ENV.PEX_PYTHON_PATH:
      # no PEX_PYTHON_PATH, PEX_PYTHON, or interpreter constraints, continue as normal
      return

  _handle_general_interpreter_selection(ENV.PEX_PYTHON_PATH, compatibility_constraints)


def bootstrap_pex(entry_point):
  from .finders import register_finders
  register_finders()
  pex_info = get_pex_info(entry_point)
  with TRACER.timed('Bootstrapping pex with maybe_reexec_pex', V=2):
    maybe_reexec_pex(pex_info.interpreter_constraints)

  from . import pex
  pex.PEX(entry_point).execute()


def bootstrap_pex_env(entry_point):
  """Bootstrap the current runtime environment using a given pex."""
  from .environment import PEXEnvironment
  from .finders import register_finders
  from .pex_info import PexInfo

  register_finders()

  PEXEnvironment(entry_point, PexInfo.from_pex(entry_point)).activate()
