# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
from distutils.core import Command
from distutils import log as logger

import pkg_resources

safe_name = pkg_resources.safe_name
safe_version = pkg_resources.safe_version

from .bin.pex import main


def safer_name(name):
  return safe_name(name).replace('-', '_')

def safer_version(version):
  return safe_version(version).replace('-', '_')


class bdist_pex(Command):
  description = 'create a pex distribution'
  user_options = [
    ('console-script=', 'c',
    "Set the entry point as to the script or console_script "
    "as defined by a any of the distributions in the pex."),
    ('entry-point=', 'm',
     "Set the entry point to module or module:symbol."),
    ('dist-dir=', 'd',
     "directory to put final built distributions in"),
    ('index-url=', 'i',
     "Additional cheeseshop indices to use to satisfy requirements."),
    ('python=', 'p',
     "python interpreter to use"),
    ('requirement=', 'r',
     "Add requirements from the given requirements file."),
  ]

  def initialize_options(self):
    self.console_script = None
    self.dist_dir = None
    self.entry_point = None
    self.index_url = None
    self.python = None
    self.requirement = None

  def finalize_options(self):
    need_options = ('dist_dir',)

    self.set_undefined_options('bdist', *zip(need_options, need_options))

  def run(self):
    pexfile_path = self._get_pexfile_path()
    logger.info('creating %s', pexfile_path)
    args = ['.', '-o', pexfile_path]

    if self.console_script:
      args.append('--console-script=%s' % self.console_script)

    if self.entry_point:
      args.append('--entry-point=%s' % self.entry_point)

    if self.index_url:
      args.append('--index-url=%s' % self.index_url)

    if self.python:
      args.append('--python=%s' % self.python)

    if self.requirement:
      args.append('--requirement=%s' % self.requirement)

    logger.debug('invoking pex with args: %r', args)
    main(args)

  def _get_pexfile_path(self):
    return os.path.join(self.dist_dir, '%s.pex' % self.pex_dist_name)

  @property
  def pex_dist_name(self):
    """Return distribution full name with - replaced with _"""
    return '-'.join((
      safer_name(self.distribution.get_name()),
      safer_version(self.distribution.get_version())))
