import os
import pprint
from distutils import log

from pex.bin.pex import configure_clp, build_pex
from pex.common import die

from setuptools import Command


class bdist_pex(Command):
  description = "create a PEX file from a source distribution"

  user_options = [
      ('bdist-all', None, 'pexify all defined entry points'),
      ('bdist-dir', None, 'the directory into which pexes will be written, default: dist.'),
      ('pex-args=', None, 'additional arguments to the pex tool'),
  ]

  boolean_options = [
    'bdist-all',
  ]

  def initialize_options(self):
    self.bdist_all = False
    self.bdist_dir = None
    self.pex_args = ''

  def finalize_options(self):
    self.pex_args = self.pex_args.split()

  def _write(self, pex_builder, name, script=None):
    builder = pex_builder.clone()

    if script is not None:
      builder.set_script(script)

    target = os.path.join(self.bdist_dir, name + '.pex')

    builder.build(target)

  def run(self):
    name = self.distribution.get_name()
    parser, options_builder = configure_clp()
    package_dir = os.path.dirname(os.path.realpath(os.path.expanduser(self.distribution.script_name)))

    if self.bdist_dir is None:
      self.bdist_dir = os.path.join(package_dir, 'dist')

    options, reqs = parser.parse_args(self.pex_args)

    if options.entry_point or options.script:
      die('Must not specify entry_point or script to --pex-args')

    reqs = [package_dir] + reqs
    pex_builder = build_pex(reqs, options, options_builder)

    if self.bdist_all:
      for entry_point in self.distribution.entry_points['console_scripts']:
        script_name = entry_point.split('=')[0].strip()
        log.info('Writing %s to %s.pex' % (script_name, script_name))
        self._write(pex_builder, script_name, script=script_name)
    else:
      if len(self.distribution.entry_points.get('console_scripts', [])) == 1:
        script_name = self.distribution.entry_points['console_scripts'][0].split('=')[0].strip()
        log.info('Writing %s to %s.pex' % (script_name, name))
        self._write(pex_builder, name, script=script_name)
      else:
        log.info('Writing environment pex into %s.pex' % name)
        self._write(pex_builder, name, script=None)
