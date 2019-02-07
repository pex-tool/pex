# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
import sys

from pex import third_party
from pex.common import safe_mkdtemp, safe_rmtree
from pex.compatibility import WINDOWS
from pex.executor import Executor
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.tracer import TRACER

__all__ = (
  'Packager'
)


def after_installation(function):
  def function_wrapper(self, *args, **kw):
    self._installed = self.run()
    if not self._installed:
      raise SetuptoolsInstallerBase.InstallFailure('Failed to install %s' % self._source_dir)
    return function(self, *args, **kw)
  return function_wrapper


class SetuptoolsInstallerBase(object):
  class Error(Exception): pass
  class InstallFailure(Error): pass
  class IncapableInterpreter(Error): pass

  def __init__(self, source_dir, interpreter=None, install_dir=None):
    """Create an installer from an unpacked source distribution in source_dir."""
    self._source_dir = source_dir
    self._install_tmp = install_dir or safe_mkdtemp()
    self._interpreter = interpreter or PythonInterpreter.get()
    self._installed = None

  @property
  def mixins(self):
    """Return a list of extra distribution names required by the `setup_command`."""
    return []

  @property
  def install_tmp(self):
    return self._install_tmp

  def setup_command(self):
    """The setup command-line to run, to be implemented by subclasses."""
    raise NotImplementedError

  @property
  def setup_py_wrapper(self):
    # NB: It would be more direct to just over-write setup.py by pre-pending the setuptools import.
    # We cannot do this however because we would then run afoul of setup.py files in the wild with
    # from __future__ imports. This mode of injecting the import works around that issue.
    return """
# We need to allow setuptools to monkeypatch distutils in case the underlying setup.py uses
# distutils; otherwise, we won't have access to distutils commands installed via the
# `distutils.commands` `entrypoints` setup metadata (which is only supported by setuptools).
# The prime example here is `bdist_wheel` offered by the wheel dist.
import setuptools

# Now execute the package's setup.py such that it sees itself as a setup.py executed via
# `python setup.py ...`
import sys
__file__ = 'setup.py'
sys.argv[0] = __file__
with open(__file__, 'rb') as fp:
  exec(fp.read())
"""

  def run(self):
    if self._installed is not None:
      return self._installed

    with TRACER.timed('Installing %s' % self._install_tmp, V=2):
      env = self._interpreter.sanitized_environment()
      mixins = OrderedSet(['setuptools'] + self.mixins)
      env['PYTHONPATH'] = os.pathsep.join(third_party.expose(mixins))
      env['__PEX_UNVENDORED__'] = '1'

      command = [self._interpreter.binary, '-s', '-'] + self.setup_command()
      try:
        Executor.execute(command,
                         env=env,
                         cwd=self._source_dir,
                         stdin_payload=self.setup_py_wrapper.encode('ascii'))
        self._installed = True
      except Executor.NonZeroExit as e:
        self._installed = False
        name = os.path.basename(self._source_dir)
        print('**** Failed to install %s (caused by: %r\n):' % (name, e), file=sys.stderr)
        print('stdout:\n%s\nstderr:\n%s\n' % (e.stdout, e.stderr), file=sys.stderr)
        return self._installed

    return self._installed

  def cleanup(self):
    safe_rmtree(self._install_tmp)


class DistributionPackager(SetuptoolsInstallerBase):
  @after_installation
  def find_distribution(self):
    dists = os.listdir(self.install_tmp)
    if len(dists) == 0:
      raise self.InstallFailure('No distributions were produced!')
    elif len(dists) > 1:
      raise self.InstallFailure('Ambiguous source distributions found: %s' % (' '.join(dists)))
    else:
      return os.path.join(self.install_tmp, dists[0])


class Packager(DistributionPackager):
  """Create a source distribution from an unpacked setup.py-based project."""

  def setup_command(self):
    if WINDOWS:
      return ['sdist', '--formats=zip', '--dist-dir=%s' % self._install_tmp]
    else:
      return ['sdist', '--formats=gztar', '--dist-dir=%s' % self._install_tmp]

  def sdist(self):
    return self.find_distribution()


class EggInstaller(DistributionPackager):
  """Create an egg distribution from an unpacked setup.py-based project."""

  def setup_command(self):
    return ['bdist_egg', '--dist-dir=%s' % self._install_tmp]

  def bdist(self):
    return self.find_distribution()


class WheelInstaller(DistributionPackager):
  """Create a wheel distribution from an unpacked setup.py-based project."""

  @property
  def mixins(self):
    return ['wheel']

  def setup_command(self):
    return ['bdist_wheel', '--dist-dir=%s' % self._install_tmp]

  def bdist(self):
    return self.find_distribution()
