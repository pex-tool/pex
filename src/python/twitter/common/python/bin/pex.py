"""
The pex.pex utility builds PEX environments and .pex files specified by
sources, requirements and their dependencies.
"""

from __future__ import print_function

from optparse import OptionParser
import os
import sys

from twitter.common.python.common import safe_delete, safe_mkdtemp
from twitter.common.python.distiller import Distiller
from twitter.common.python.fetcher import Fetcher, PyPIFetcher
from twitter.common.python.installer import Installer
from twitter.common.python.resolver import Resolver
from twitter.common.python.pex_builder import PEXBuilder
from twitter.common.python.pex import PEX
from twitter.common.python.tracer import Tracer


CANNOT_PARSE_REQUIREMENT = 100
CANNOT_DISTILL = 101


def die(msg, error_code=1):
  print(msg, file=sys.stderr)
  sys.exit(error_code)


def parse_bool(option, opt_str, _, parser):
  setattr(parser.values, option.dest, not opt_str.startswith('--no'))


def configure_clp():
  usage = (
      '%prog [options]\n\n'
      '%prog builds a PEX (Python Executable) file based on the given specifications: '
      'sources, requirements, their dependencies and other options')

  parser = OptionParser(usage=usage, version='%prog 0.2')

  parser.add_option(
      '--pypi', '--no-pypi',
      dest='pypi',
      default=True,
      action='callback',
      callback=parse_bool,
      help='Whether to use pypi to resolve dependencies; Default: use pypi')

  parser.add_option(
      '--cache-dir',
      dest='cache_dir',
      default=os.path.expanduser('~/.pex/install'),
      help='The local cache directory to use for speeding up requirement '
           'lookups; Default: ~/.pex/install')

  parser.add_option(
      '-p', '--pex-name',
      dest='pex_name',
      default=None,
      help='The name of the generated .pex file: Omiting this will run PEX '
           'immediately and not save it to a file')

  parser.add_option(
      '-e', '--entry-point',
      dest='entry_point',
      default=None,
      help='The entry point for this pex; Omiting this will enter the python '
           'REPL with sources and requirements available for import')

  parser.add_option(
      '-r', '--requirement',
      dest='requirements',
      metavar='REQUIREMENT',
      default=[],
      action='append',
      help='requirement to be included; may be specified multiple times.')

  parser.add_option(
      '--repo',
      dest='repos',
      metavar='PATH',
      default=[],
      action='append',
      help='Additional repository path (directory or URL) to look for requirements.')

  parser.add_option(
      '-s', '--source-dir',
      dest='source_dirs',
      metavar='DIR',
      default=[],
      action='append',
      help='Source to be packaged; This <DIR> should be a pip-installable project '
           'with a setup.py.')

  parser.add_option(
      '-v', '--verbosity',
      dest='verbosity',
      default=False,
      action='store_true',
      help='Turn on logging verbosity.')

  return parser


def build_pex(args, options):
  pex_builder = PEXBuilder(path=safe_mkdtemp())

  fetchers = [Fetcher(options.repos)]

  if options.pypi:
    fetchers.append(PyPIFetcher())

  resolver = Resolver(cache=options.cache_dir, fetchers=fetchers, install_cache=options.cache_dir)

  if options.requirements:
    print('Resolving requirements:')
    for req in options.requirements:
      print('  - %s' % req)

  resolveds = resolver.resolve(options.requirements)

  for pkg in resolveds:
    print('Resolved distribution: %s [%s]' % (pkg, pkg.location))
    pex_builder.add_distribution(pkg)
    pex_builder.add_requirement(pkg.as_requirement())

  for source_dir in options.source_dirs:
    print('Distilling %s into egg...' % source_dir, end='\r')
    dist = Installer(source_dir).distribution()
    if not dist:
      die('Failed to run installer for %s' % source_dir, CANNOT_DISTILL)
    egg_path = Distiller(dist).distill()
    if not egg_path:
      die('Failed to distill %s into egg' % dist, CANNOT_DISTILL)
    pex_builder.add_egg(egg_path)
    print('Successfully distilled %s into %s' % (source_dir, egg_path))

  if options.entry_point is not None:
    print('Setting entry point to %s' % options.entry_point)
    pex_builder.info.entry_point = options.entry_point
  else:
    print('Creating environment PEX.')

  if options.pex_name is not None:
    print('Saving PEX file to %s' % options.pex_name)
    tmp_name = options.pex_name + '~'
    safe_delete(tmp_name)
    pex_builder.build(tmp_name)
    os.rename(tmp_name, options.pex_name)
  else:
    pex_builder.freeze()
    print('Running PEX file at %s with args %s' % (pex_builder.path(), args))
    pex = PEX(pex_builder.path())
    return pex.run(args=list(args))

  return 0


def main():
  parser = configure_clp()
  options, args = parser.parse_args()
  verbosity = 5 if options.verbosity else -1

  with Tracer.env_override(
      PEX_VERBOSE=verbosity,
      TWITTER_COMMON_PYTHON_HTTP=verbosity,
      PYTHON_VERBOSE=verbosity):

    sys.exit(build_pex(args, options))
