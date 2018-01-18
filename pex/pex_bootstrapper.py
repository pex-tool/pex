# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import print_function

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


def find_compatible_interpreters(pex_python_path, compatibility_constraints):
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
    if not os.getenv('PATH', ''):
      # no $PATH, use sys.executable
      interpreters = [PythonInterpreter.get()]
    else:
      # get all qualifying interpreters found in $PATH
      interpreters = PythonInterpreter.all()

  return list(matched_interpreters(
    interpreters, compatibility_constraints, meet_all_constraints=True))


def _select_pex_python_interpreter(target_python, compatibility_constraints):
  target = find_in_path(target_python)

  if not target:
    die('Failed to find interpreter specified by PEX_PYTHON: %s' % target)
  if compatibility_constraints:
    pi = PythonInterpreter.from_binary(target)
    if not list(matched_interpreters([pi], compatibility_constraints, meet_all_constraints=True)):
      die('Interpreter specified by PEX_PYTHON (%s) is not compatible with specified '
          'interpreter constraints: %s' % (target, str(compatibility_constraints)))
  if not os.path.exists(target):
    die('Target interpreter specified by PEX_PYTHON %s does not exist. Exiting.' % target)
  return target


def _select_interpreter(pex_python_path, compatibility_constraints):
  compatible_interpreters = find_compatible_interpreters(
    pex_python_path, compatibility_constraints)

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
  compatible interpreters can be found on said path. If neither variable is set, fall through to
  plain pex execution using PATH searching or the currently executing interpreter.

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
                                              compatibility_constraints)
    elif ENV.PEX_PYTHON_PATH:
      target = _select_interpreter(ENV.PEX_PYTHON_PATH, compatibility_constraints)

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


def bootstrap_pex(entry_point):
  from .finders import register_finders
  register_finders()
  pex_info = get_pex_info(entry_point)
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
