# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================
from __future__ import absolute_import

import logging
import os
import sys
import tempfile
from zipimport import zipimporter

from .compatibility import to_bytes
from .common import chmod_plus_x, safe_mkdir, Chroot
from .interpreter import PythonInterpreter
from .marshaller import CodeMarshaller
from .pex_info import PexInfo
from .translator import dist_from_egg
from .util import DistributionHelper

from pkg_resources import (
    DefaultProvider,
    Distribution,
    EggMetadata,
    Requirement,
    ZipProvider,
    get_provider,
)


BOOTSTRAP_ENVIRONMENT = b"""
import os
import sys

__entry_point__ = None
if '__file__' in locals() and __file__ is not None:
  __entry_point__ = os.path.dirname(__file__)
elif '__loader__' in locals():
  from zipimport import zipimporter
  from pkgutil import ImpLoader
  if hasattr(__loader__, 'archive'):
    __entry_point__ = __loader__.archive
  elif isinstance(__loader__, ImpLoader):
    __entry_point__ = os.path.dirname(__loader__.get_filename())

if __entry_point__ is None:
  sys.stderr.write('Could not launch python executable!\\n')
  sys.exit(2)

sys.path[0] = os.path.abspath(sys.path[0])
sys.path.insert(0, os.path.abspath(os.path.join(__entry_point__, '.bootstrap')))

from _twitter_common_python.pex_bootstrapper import bootstrap_pex
bootstrap_pex(__entry_point__)
"""

class PEXBuilder(object):
  class InvalidDependency(Exception): pass
  class InvalidExecutableSpecification(Exception): pass

  BOOTSTRAP_DIR = ".bootstrap"

  def __init__(self, path=None, interpreter=None, chroot=None, pex_info=None):
    self._chroot = chroot or Chroot(path or tempfile.mkdtemp())
    self._pex_info = pex_info or PexInfo.default()
    self._frozen = False
    self._interpreter = interpreter or PythonInterpreter.get()
    self._logger = logging.getLogger(__name__)

  def chroot(self):
    return self._chroot

  def clone(self, into=None):
    chroot_clone = self._chroot.clone(into=into)
    return PEXBuilder(chroot=chroot_clone, interpreter=self._interpreter,
                      pex_info=PexInfo(content=self._pex_info.dump()))

  def path(self):
    return self.chroot().path()

  @property
  def info(self):
    return self._pex_info

  @info.setter
  def info(self, value):
    if not isinstance(value, PexInfo):
      raise TypeError('PEXBuilder.info must be a PexInfo!')
    self._pex_info = value

  def add_source(self, filename, env_filename):
    self._chroot.link(filename, env_filename, "source")
    if filename.endswith('.py'):
      env_filename_pyc = os.path.splitext(env_filename)[0] + '.pyc'
      with open(filename) as fp:
        pyc_object = CodeMarshaller.from_py(fp.read(), env_filename)
      self._chroot.write(pyc_object.to_pyc(), env_filename_pyc, 'source')

  def add_resource(self, filename, env_filename):
    self._chroot.link(filename, env_filename, "resource")

  def add_requirement(self, req, dynamic=False, repo=None):
    self._pex_info.add_requirement(req, repo=repo, dynamic=dynamic)

  def add_dependency_file(self, filename, env_filename):
    # TODO(wickman) This is broken.  The build cache abstraction just breaks down here.
    if filename.endswith('.egg'):
      self.add_egg(filename)
    else:
      self._chroot.link(filename, os.path.join(self._pex_info.internal_cache, env_filename))

  def set_entry_point(self, entry_point):
    self.info.entry_point = entry_point

  def add_egg(self, egg):
    """
      helper for add_distribution
    """
    metadata = EggMetadata(zipimporter(egg))
    dist = Distribution.from_filename(egg, metadata)
    self.add_distribution(dist)
    self.add_requirement(dist.as_requirement(), dynamic=False, repo=None)

  def add_distribution(self, dist):
    if not dist.location.endswith('.egg'):
      raise PEXBuilder.InvalidDependency('Non-egg dependencies not yet supported.')
    self._chroot.link(dist.location,
      os.path.join(self._pex_info.internal_cache, os.path.basename(dist.location)))

  def set_executable(self, filename, env_filename=None):
    if env_filename is None:
      env_filename = os.path.basename(filename)
    if self._chroot.get("executable"):
      raise PEXBuilder.InvalidExecutableSpecification(
          "Setting executable on a PEXBuilder that already has one!")
    self._chroot.link(filename, env_filename, "executable")
    entry_point = env_filename
    entry_point.replace(os.path.sep, '.')
    self._pex_info.entry_point = entry_point.rpartition('.')[0]

  def _prepare_inits(self):
    relative_digest = self._chroot.get("source")
    init_digest = set()
    for path in relative_digest:
      split_path = path.split(os.path.sep)
      for k in range(1, len(split_path)):
        sub_path = os.path.sep.join(split_path[0:k] + ['__init__.py'])
        if sub_path not in relative_digest and sub_path not in init_digest:
          self._chroot.write("__import__('pkg_resources').declare_namespace(__name__)",
              sub_path)
          init_digest.add(sub_path)

  def _prepare_manifest(self):
    self._chroot.write(self._pex_info.dump().encode('utf-8'), PexInfo.PATH, label='manifest')

  def _prepare_main(self):
    self._chroot.write(BOOTSTRAP_ENVIRONMENT, '__main__.py', label='main')

  # TODO(wickman) Ideally we include twitter.common.python and twitter.common-core via the eggs
  # rather than this hackish .bootstrap mechanism.  (Furthermore, we'll probably need to include
  # both a pkg_resources and lib2to3 version of pkg_resources.)
  def _prepare_bootstrap(self):
    """
      Write enough of distribute into the .pex .bootstrap directory so that
      we can be fully self-contained.
    """
    distribute = dist_from_egg(self._interpreter.distribute)
    for fn, content_stream in DistributionHelper.walk_data(distribute):
      # TODO(wickman)  Investigate if the omission of setuptools proper causes failures to
      # build eggs.
      if fn == 'pkg_resources.py':
        self._chroot.write(content_stream.read(),
            os.path.join(self.BOOTSTRAP_DIR, 'pkg_resources.py'), 'resource')
    libraries = (
      'twitter.common.python',
      'twitter.common.python.http',
    )
    for name in libraries:
      dirname = name.replace('twitter.common.python', '_twitter_common_python').replace('.', '/')
      provider = get_provider(name)
      if not isinstance(provider, DefaultProvider):
        mod = __import__(name, fromlist=['wutttt'])
        provider = ZipProvider(mod)
      for fn in provider.resource_listdir(''):
        if fn.endswith('.py'):
          self._chroot.write(provider.get_resource_string(name, fn),
            os.path.join(self.BOOTSTRAP_DIR, dirname, fn), 'resource')

  def freeze(self):
    if self._frozen:
      return
    self._prepare_inits()
    self._prepare_manifest()
    self._prepare_bootstrap()
    self._prepare_main()
    self._frozen = True

  def build(self, filename):
    self.freeze()
    try:
      os.unlink(filename + '~')
      self._logger.warn('Previous binary unexpectedly exists, cleaning: %s' % (filename + '~'))
    except OSError:
      # The expectation is that the file does not exist, so continue
      pass
    if os.path.dirname(filename):
      safe_mkdir(os.path.dirname(filename))
    with open(filename + '~', 'ab') as pexfile:
      assert os.path.getsize(pexfile.name) == 0
      pexfile.write(to_bytes('%s\n' % self._interpreter.identity.hashbang()))
    self._chroot.zip(filename + '~', mode='a')
    if os.path.exists(filename):
      os.unlink(filename)
    os.rename(filename + '~', filename)
    chmod_plus_x(filename)


class PEXBuilderHelper(object):
  """
  PEXBuilderHelper implements the pex.pex utility which builds a .pex file specified by
  sources, requirements and their dependencies and other options
  """

  from collections import namedtuple
  logger = logging.getLogger(__name__)
  error_names = ("NOTHING_TO_BUILD", "NOT_IMPLEMENTED")
  error_code = namedtuple('Enum', error_names)._make(
    map(lambda x: x + 100, range(len(error_names)))
  )

  @classmethod
  def get_all_valid_reqs(cls, requirements, requirements_txt):
    from collections import namedtuple
    import re
    numbered_item = namedtuple("numbered_item", ["position", "data"])
    numbered_list = lambda dataset: [numbered_item(*ni) for ni in enumerate(dataset)]
    named_dataset = namedtuple("named_dataset", ["name", "dataset"])
    inputs = [
      named_dataset(name="command line", dataset=numbered_list(requirements)),
    ]
    if requirements_txt is not None:
      file_lines = re.split("[\n\r]", open(requirements_txt).read())
      inputs.append(named_dataset(
        name="file: {0}".format(requirements_txt), dataset=numbered_list(file_lines)
      ))
    valid_reqs = []
    whitespace = re.compile("^\s*$")
    for name, dataset in inputs:
      for position, req in dataset:
        try:
          Requirement.parse(req)
          valid_reqs.append(req)
        except ValueError:
          if whitespace.match(req) is None: # Don't warn if empty string or whitespace
            cls.logger.warn("Invalid requirement \"{0}\" at " \
                        "position {1} from {2}\n".format(req, position + 1, name))
    return valid_reqs

  @classmethod
  def configure_clp(cls):
    from optparse import OptionParser
    usage = "%prog [options]\n\n" \
    "%prog builds a PEX (Python Executable) file based on the given specifications: " \
    "sources, requirements, their dependencies and other options"

    parser = OptionParser(usage=usage, version="%prog 0.1.0")
    parser.add_option("--no-pypi", dest="use_pypi", default=True, action="store_false",
                      help="Dont use pypi to resolve dependencies; Default: use pypi")
    parser.add_option("--cache-dir", dest="cache_dir", default=os.path.expanduser("~/.pex/install"),
                      help="The local cache directory to use for speeding up requirement " \
                           "lookups; Default: ~/.pex/install")
    parser.add_option("--pex-name", dest="pex_name", default=None,
                      help="The name of the generated .pex file: Omiting this will run PEX " \
                           "immediately and not save it to a file")
    parser.add_option("--entry-point", dest="entry_point", default=None,
                      help="The entry point for this pex; Omiting this will enter the python " \
                           "IDLE with sources and requirements available for import")
    parser.add_option("--requirements-txt", dest="requirements_txt", metavar="FILE", default=None,
                      help="requirements.txt file listing the dependencies; This is in " \
                           "addition to requirements specified by -r; Unless your sources " \
                           "have no requirements, specify this or use -r. Default None")
    parser.add_option("-r", "--requirement", dest="requirements", metavar="REQUIREMENT",
                      default=[], action="append",
                      help="requirement to be included; include as many as needed in addition " \
                           "to requirements from --requirements-txt")
    # TODO{sgeorge}: allow lightweight PEXs (or PEXs with dynamically resolved reqs)
    parser.add_option("--lightweight", dest="lightweight", default=False, action="store_true",
                      help="Builds a lightweight PEX with requirements not resolved until " \
                           "runtime; Not implemented")
    parser.add_option("--source-dir", dest="source_dirs", metavar="DIR",
                      default=[], action="append",
                      help="Source to be packaged; This <DIR> should be pip-installable i.e. " \
                           "it should include a setup.py; Omiting this will create a PEX of " \
                           "requirements alone")
    # TODO{sgeorge}: allow repos to be specified
    parser.add_option("--repo", dest="repos", metavar="TYPE:URL", default=[], action="append",
                      help="repository spec for resolving dependencies; Not implemented")

    cls.configure_logging_options(parser)
    return parser

  @classmethod
  def configure_logging_options(cls, parser):
    parser.add_option("--log-file", dest="log_file", metavar="FILE", default=None,
                      help="Log messages to FILE; Default to stdout")
    parser.add_option("--log-level", dest="log_level", default="warn",
                      help="Log level as text (one of info, warn, error, critical)")

  @classmethod
  def process_logging_options(cls, options):
    numeric_level = getattr(logging, options.log_level.upper(), None)
    if not isinstance(numeric_level, int):
      raise ValueError('Invalid log level: %s' % options.log_level)
    if options.log_file is not None:
      logging.basicConfig(level=numeric_level, file=options.log_file)
    else:
      logging.basicConfig(level=numeric_level) # file=sys.stdout

  @classmethod
  def exit_on_erroneous_inputs(cls, options, parser):
    if len(options.source_dirs) == 0 and \
        options.requirements_txt is None and len(options.requirements) == 0:
      cls.logger.error("Nothing to build (or run)!")
      parser.print_help()
      sys.exit(cls.error_code.NOTHING_TO_BUILD)
    if options.lightweight:
      cls.logger.error("Lightweight PEXs not implemented! Bug us!!")
      sys.exit(cls.error_code.NOT_IMPLEMENTED)

  @classmethod
  def main(cls):
    from .distiller import Distiller
    from .fetcher import Fetcher, PyPIFetcher
    from .installer import Installer
    from .resolver import Resolver

    parser = cls.configure_clp()
    options, args = parser.parse_args()
    cls.process_logging_options(options)
    cls.exit_on_erroneous_inputs(options, parser)

    pex_builder = PEXBuilder()

    fetchers = [Fetcher(options.repos)]
    if options.use_pypi:
      fetchers.append(PyPIFetcher())
    resolver = Resolver(cache=options.cache_dir, fetchers=fetchers, install_cache=options.cache_dir)
    reqs = cls.get_all_valid_reqs(options.requirements, options.requirements_txt)
    cls.logger.info("Requirements specified: " + str(reqs))
    resolveds = resolver.resolve(reqs)
    cls.logger.info("Resolved requirements: " + str(resolveds))
    for pkg in resolveds:
      cls.logger.info("Adding to PEX: Distribution: {0}".format(pkg))
      pex_builder.add_distribution(pkg)
      pex_builder.add_requirement(pkg.as_requirement())
    for source_dir in options.source_dirs:
      dist = Installer(source_dir).distribution()
      egg_path = Distiller(dist).distill()
      cls.logger.info("Adding source dir to PEX: {0} distilled into egg {1}".format(
        source_dir, egg_path)
      )
      pex_builder.add_egg(egg_path)
    if options.entry_point is not None:
      if options.entry_point.endswith(".py"):
        cls.logger.info("Adding entry point to PEX: File: {0}".format(options.entry_point))
        pex_builder.set_executable(options.entry_point)
      elif ":" in options.entry_point:
        cls.logger.info("Adding entry point to PEX: Function: {0}".format(options.entry_point))
        pex_builder.info.entry_point = options.entry_point
      else:
        cls.logger.warn("Invalid entry point: {0}".format(options.entry_point))
    if options.pex_name is not None:
      cls.logger.info("Saving PEX file at {0}.pex".format(options.pex_name))
      pex_builder.build(options.pex_name + '.pex')
    else:
      pex_builder.freeze()
      cls.logger.info("Running PEX file at {0} with args {1}".format(pex_builder.path(), args))
      from .pex import PEX
      pex = PEX(pex_builder.path())
      return pex.run(args=list(args))

    logging.shutdown()


def main():
  """Entry point of pex.pex"""
  PEXBuilderHelper.main()
