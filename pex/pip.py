# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

from collections import deque

from pex.compatibility import urlparse
from pex.distribution_target import DistributionTarget
from pex.jobs import spawn_python_job
from pex.variables import ENV


def _spawn_pip_isolated(args, cache=None, interpreter=None):
  pip_args = ['-m', 'pip', '--disable-pip-version-check', '--isolated', '--exists-action', 'i']

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

  return spawn_python_job(
    args=pip_args + args,
    interpreter=interpreter,
    expose=['pip', 'setuptools', 'wheel']
  )


def _calculate_package_index_options(indexes=None, find_links=None):
  trusted_hosts = []

  def maybe_trust_insecure_host(url):
    url_info = urlparse.urlparse(url)
    if 'http' == url_info.scheme:
      # Implicitly trust explicitly asked for http indexes and find_links repos instead of requiring
      # seperate trust configuration.
      trusted_hosts.append(url_info.netloc)
    return url

  # N.B.: We interpret None to mean accept pip index defaults, [] to mean turn off all index use.
  if indexes is not None:
    if len(indexes) == 0:
      yield '--no-index'
    else:
      all_indexes = deque(indexes)
      yield '--index-url'
      yield maybe_trust_insecure_host(all_indexes.popleft())
      if all_indexes:
        for extra_index in all_indexes:
          yield '--extra-index-url'
          yield maybe_trust_insecure_host(extra_index)

  if find_links:
    for find_link_url in find_links:
      yield '--find-links'
      yield maybe_trust_insecure_host(find_link_url)

  for trusted_host in trusted_hosts:
    yield '--trusted-host'
    yield trusted_host


def spawn_download_distributions(download_dir,
                                 requirements=None,
                                 requirement_files=None,
                                 constraint_files=None,
                                 allow_prereleases=False,
                                 transitive=True,
                                 target=None,
                                 indexes=None,
                                 find_links=None,
                                 cache=None,
                                 build=True,
                                 use_wheel=True):

  target = target or DistributionTarget.current()

  platform = target.get_platform()
  if not use_wheel:
    if not build:
      raise ValueError('Cannot both ignore wheels (use_wheel=False) and refrain from building '
                       'distributions (build=False).')
    elif target.is_foreign:
      raise ValueError('Cannot ignore wheels (use_wheel=False) when resolving for a foreign '
                       'platform: {}'.format(platform))

  download_cmd = ['download', '--dest', download_dir]
  download_cmd.extend(_calculate_package_index_options(indexes=indexes, find_links=find_links))

  if target.is_foreign:
    # We're either resolving for a different host / platform or a different interpreter for the
    # current platform that we have no access to; so we need to let pip know and not otherwise
    # pickup platform info from the interpreter we execute pip with.
    download_cmd.extend(['--platform', platform.platform])
    download_cmd.extend(['--implementation', platform.impl])
    download_cmd.extend(['--python-version', platform.version])
    download_cmd.extend(['--abi', platform.abi])

  if target.is_foreign or not build:
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

  return _spawn_pip_isolated(download_cmd, cache=cache, interpreter=target.get_interpreter())


def spawn_build_wheels(distributions,
                       wheel_dir,
                       interpreter=None,
                       indexes=None,
                       find_links=None,
                       cache=None):

  wheel_cmd = ['wheel', '--no-deps', '--wheel-dir', wheel_dir]

  # If the build is PEP-517 compliant it may need to resolve build requirements.
  wheel_cmd.extend(_calculate_package_index_options(indexes=indexes, find_links=find_links))

  wheel_cmd.extend(distributions)
  return _spawn_pip_isolated(wheel_cmd, cache=cache, interpreter=interpreter)


def spawn_install_wheel(wheel,
                        install_dir,
                        compile=False,
                        overwrite=False,
                        cache=None,
                        target=None):

  target = target or DistributionTarget.current()

  install_cmd = [
    'install',
    '--no-deps',
    '--no-index',
    '--only-binary', ':all:',
    '--target', install_dir
  ]

  interpreter = target.get_interpreter()
  if target.is_foreign:
    if compile:
      raise ValueError('Cannot compile bytecode for {} using {} because the wheel has a foreign '
                       'platform.'.format(wheel, interpreter))

    # We're installing a wheel for a foreign platform. This is just an unpacking operation though;
    # so we don't actually need to perform it with a target platform compatible interpreter.
    install_cmd.append('--ignore-requires-python')

  install_cmd.append('--compile' if compile else '--no-compile')
  if overwrite:
    install_cmd.extend(['--upgrade', '--force-reinstall'])
  install_cmd.append(wheel)
  return _spawn_pip_isolated(install_cmd, cache=cache, interpreter=interpreter)
