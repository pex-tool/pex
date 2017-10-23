# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys

from .common import open_zip
from .interpreter import PythonInterpreter
from .interpreter_constraints import (
    lowest_version_interpreter,
    matched_interpreters,
    parse_interpreter_constraints
)

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


def _find_compatible_interpreter_in_pex_python_path(target_python_path, compatibility_constraints):
  parsed_compatibility_constraints = parse_interpreter_constraints(compatibility_constraints)
  try_binaries = []
  for binary in target_python_path.split(os.pathsep):
    try_binaries.append(PythonInterpreter.from_binary(binary))
  compatible_interpreters = list(matched_interpreters(
    try_binaries, parsed_compatibility_constraints, meet_all_constraints=True))
  return lowest_version_interpreter(compatible_interpreters)


def maybe_reexec_pex(compatibility_constraints=None):
  from .variables import ENV
  if not ENV.PEX_PYTHON_PATH or not compatibility_constraints:
    return

  from .common import die
  from .tracer import TRACER

  target_python_path = ENV.PEX_PYTHON_PATH
  lowest_version_compatible_interpreter = _find_compatible_interpreter_in_pex_python_path(
    target_python_path, compatibility_constraints)
  target = lowest_version_compatible_interpreter.binary
  if not target:
    die('Failed to find compatible interpreter in PEX_PYTHON_PATH for constraints: %s'
        % compatibility_constraints)
  if os.path.exists(target) and os.path.realpath(target) != os.path.realpath(sys.executable):
    TRACER.log('Detected PEX_PYTHON_PATH, re-exec to %s' % target)
    ENV.delete('PEX_PYTHON_PATH')
    os.execve(target, [target] + sys.argv, ENV.copy())


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
