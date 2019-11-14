# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
from collections import deque

from pex import third_party
from pex.interpreter import PythonInterpreter
from pex.platforms import Platform
from pex.variables import ENV


class PipError(Exception):
  """Indicates an error running a pip command."""


def execute_pip_isolated(args, cache=None, interpreter=None):
  env = os.environ.copy()
  env['__PEX_UNVENDORED__'] = '1'

  pythonpath = third_party.expose(['pip', 'setuptools', 'wheel'])

  pip_args = ['-m', 'pip', '--disable-pip-version-check', '--isolated']

  # The max pip verbosity is -vvv and for pex it's -vvvvvvvvv; so we scale down by a factor of 3.
  verbosity = ENV.PEX_VERBOSE // 3
  if verbosity > 0:
    pip_args.append('-{}'.format('v' * verbosity))
  else:
    pip_args.append('-q')

  if cache:
    pip_args.extend(['--cache-dir', cache])
  else:
    pip_args.append('--no-cache-dir')

  pip_cmd = pip_args + args

  interpreter = interpreter or PythonInterpreter.get()
  cmd, process = interpreter.open_process(args=pip_cmd, pythonpath=pythonpath, env=env)
  if process.wait() != 0:
    raise PipError('Executing {} failed with {}'.format(' '.join(cmd), process.returncode))


def _calculate_package_index_options(indexes=None, find_links=None):
  # N.B.: We interpret None to mean accept pip index defaults, [] to mean turn off all index use.
  if indexes is not None:
    if len(indexes) == 0:
      yield '--no-index'
    else:
      all_indexes = deque(indexes)
      yield '--index-url'
      yield all_indexes.popleft()
      if all_indexes:
        for extra_index in all_indexes:
          yield '--extra-index-url'
          yield extra_index

  if find_links:
    for find_link_url in find_links:
      yield '--find-links'
      yield find_link_url


def download_distributions(target,
                           requirements=None,
                           requirement_files=None,
                           constraint_files=None,
                           allow_prereleases=False,
                           transitive=True,
                           interpreter=None,
                           platform=None,
                           indexes=None,
                           find_links=None,
                           cache=None,
                           build=True,
                           use_wheel=True):

  download_cmd = ['download', '--dest', target]
  download_cmd.extend(_calculate_package_index_options(indexes=indexes, find_links=find_links))

  if platform:
    # TODO(John Sirois): Consider moving this parsing up to the CLI and switching the API to take
    # an (extended) `Platform` object instead of a string.
    platform_info = Platform.create(platform)
    if not platform_info.is_extended:
      raise PipError('Can only download distributions for fully specified platforms, given {!r}.'
                     .format(platform))

    foreign_platform = platform_info != Platform.of_interpreter(interpreter)
    if foreign_platform:
      # We're either resolving for a different host / platform or a different interpreter for the
      # current platform that we have no access to; so we need to let pip know and not otherwise
      # pickup platform info from the interpreter we execute pip with.
      download_cmd.extend(['--platform', platform_info.platform])
      download_cmd.extend(['--implementation', platform_info.impl])
      download_cmd.extend(['--python-version', platform_info.version])
      download_cmd.extend(['--abi', platform_info.abi])
  else:
    foreign_platform = False

  if not use_wheel:
    if not build:
      raise PipError('Cannot both ignore wheels (use_wheel=False) and refrain from building '
                     'distributions (build=False).')
    elif foreign_platform:
      raise PipError('Cannot ignore wheels (use_wheel=False) when resolving for a foreign '
                     'platform: {}'.format(platform))

  if foreign_platform or not build:
    download_cmd.extend(['--only-binary', ':all:'])

  if not use_wheel:
    download_cmd.extend(['--no-binary', ':all:'])

  if allow_prereleases:
    download_cmd.append('--pre')

  if not transitive:
    download_cmd.append('--no-deps')

  if requirement_files:
    for requirement_file in requirement_files:
      download_cmd.extend(['--requirement', requirement_file])

  if constraint_files:
    for constraint_file in constraint_files:
      download_cmd.extend(['--constraint', constraint_file])

  download_cmd.extend(requirements)

  execute_pip_isolated(download_cmd, cache=cache, interpreter=interpreter)


def build_wheels(distributions,
                 target,
                 interpreter=None,
                 indexes=None,
                 find_links=None,
                 cache=None):
  wheel_cmd = ['wheel', '--no-deps', '--wheel-dir', target]

  # If the build is PEP-517 compliant it may need to resolve build requirements.
  wheel_cmd.extend(_calculate_package_index_options(indexes=indexes, find_links=find_links))

  wheel_cmd.extend(distributions)
  execute_pip_isolated(wheel_cmd, cache=cache, interpreter=interpreter)


def install_wheel(wheel, target, compile=False, overwrite=False, cache=None, interpreter=None):
  install_cmd = ['install', '--no-deps', '--no-index', '--only-binary', ':all:', '--target', target]
  install_cmd.append('--compile' if compile else '--no-compile')
  if overwrite:
    install_cmd.extend(['--upgrade', '--force-reinstall'])
  install_cmd.append(wheel)
  execute_pip_isolated(install_cmd, cache=cache, interpreter=interpreter)
