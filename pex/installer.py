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
from pex.tracer import TRACER

__all__ = (
  'Packager'
)


def after_installation(function):
  def function_wrapper(self, *args, **kw):
    self._installed = self.run()
    if not self._installed:
      raise InstallerBase.InstallFailure('Failed to install %s' % self._source_dir)
    return function(self, *args, **kw)
  return function_wrapper


class InstallerBase(object):
  class Error(Exception): pass
  class InstallFailure(Error): pass
  class IncapableInterpreter(Error): pass

  def __init__(self, source_dir, interpreter=None, install_dir=None):
    """Create an installer from an unpacked source distribution in source_dir."""
    self._source_dir = source_dir
    self._install_tmp = install_dir or safe_mkdtemp()
    self._installed = None
    self._interpreter = interpreter or PythonInterpreter.get()
    if not self._interpreter.satisfies(self.mixins):
      raise self.IncapableInterpreter('Interpreter %s not capable of running %s' % (
          self._interpreter.binary, self.__class__.__name__))

  @property
  def mixins(self):
    """Return a list of requirements to load into the setup script prior to invocation."""
    raise NotImplementedError()

  @property
  def install_tmp(self):
    return self._install_tmp

  def _setup_command(self):
    """the setup command-line to run, to be implemented by subclasses."""
    raise NotImplementedError

  @property
  def bootstrap_script(self):
    return """
import sys
sys.path.insert(0, {root!r})

# Expose vendored mixin path_items (setuptools, wheel, etc.) directly to the package's setup.py.
from pex import third_party
third_party.install(root={root!r}, expose={mixins!r})

# Now execute the package's setup.py such that it sees itself as a setup.py executed via
# `python setup.py ...`
__file__ = 'setup.py'
sys.argv[0] = __file__
with open(__file__, 'rb') as fp:
  exec(fp.read())
""".format(root=third_party.isolated(), mixins=self.mixins)

  def run(self):
    if self._installed is not None:
      return self._installed

    with TRACER.timed('Installing %s' % self._install_tmp, V=2):
      command = [self._interpreter.binary, '-sE', '-'] + self._setup_command()
      try:
        Executor.execute(command,
                         env=self._interpreter.sanitized_environment(),
                         cwd=self._source_dir,
                         stdin_payload=self.bootstrap_script.encode('ascii'))
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


class DistributionPackager(InstallerBase):
  @property
  def mixins(self):
    return ['setuptools']

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

  def _setup_command(self):
    if WINDOWS:
      return ['sdist', '--formats=zip', '--dist-dir=%s' % self._install_tmp]
    else:
      return ['sdist', '--formats=gztar', '--dist-dir=%s' % self._install_tmp]

  @after_installation
  def sdist(self):
    return self.find_distribution()


class EggInstaller(DistributionPackager):
  """Create an egg distribution from an unpacked setup.py-based project."""

  def _setup_command(self):
    return ['bdist_egg', '--dist-dir=%s' % self._install_tmp]

  @after_installation
  def bdist(self):
    return self.find_distribution()


class WheelInstaller(DistributionPackager):
  """Create a wheel distribution from an unpacked setup.py-based project."""

  @property
  def mixins(self):
    return ['setuptools', 'wheel']

  def _setup_command(self):
    return ['bdist_wheel', '--dist-dir=%s' % self._install_tmp]

  @after_installation
  def bdist(self):
    return self.find_distribution()
