from __future__ import absolute_import, print_function

import ast
import os
import sys
import tempfile
import zipfile

from .common import open_zip, safe_mkdir

from pkg_resources import Distribution, get_build_platform


NAMESPACE_STUB = """
try:
  __import__('pkg_resources').declare_namespace(__name__)
except ImportError:
  from sys import stderr
  stderr.write('Unable to declare namespace for %s\\n' % __name__)
  stderr.write('This package may not work!\\n')
"""

# TODO(wickman)  Pros and cons of os.unlink after load_dynamic?
NATIVE_STUB = """
def __bootstrap__():
  import contextlib, shutil
  import os, zipfile
  import sys, imp, tempfile
  try:
    from cStringIO import StringIO
  except ImportError:
    try:
      from StringIO import StringIO
    except ImportError:
      from io import BytesIO as StringIO

  def split_existing(path):
    def generate_prefixes(path):
      if path in ('', os.path.sep): return
      for head in generate_prefixes(os.path.split(path)[0]):
        yield head
      yield path
    subpath = None
    for prefix in generate_prefixes(path):
      if not os.path.lexists(prefix):
        break
      subpath = prefix
    return (subpath, os.path.relpath(path, subpath))

  global __bootstrap__, __loader__, __file__
  real_file = os.path.splitext(__file__)[0] + '%(extension)s'
  archive, archive_name = split_existing(real_file)

  try:
    fd, name = tempfile.mkstemp()
    with contextlib.closing(zipfile.ZipFile(archive)) as zf:
      with contextlib.closing(zf.open(archive_name)) as zi:
        with os.fdopen(fd, 'wb') as fp:
          shutil.copyfileobj(zi, fp)

    __file__ = name
    __loader__ = None
    del __bootstrap__, __loader__
    imp.load_dynamic(__name__, __file__)
  finally:
    os.unlink(name)

__bootstrap__()
"""


class Distiller(object):
  """
    Distill into an egg a distribution installed anywhere on the system
    (e.g. site-packages or newly installed from twitter.common.python.installer
    Installer)

    >>> from twitter.common.python.installer import Installer
    >>> from twitter.common.python.distiller import Distiller
    >>> from twitter.common.python.http import Web, SourceLink
    >>> psutil_link = SourceLink('http://psutil.googlecode.com/files/psutil-0.6.1.tar.gz',
    ...                          opener=Web())
    >>> psutil_dist = Installer(psutil_link.fetch()).distribution()
    >>> Distiller(psutil_dist).distill()
    Writing native stub for _psutil_linux.so
    Writing native stub for _psutil_posix.so
    Skipping file outside of top_level: psutil-0.6.1-py2.7.egg-info/SOURCES.txt
    Skipping file outside of top_level: psutil-0.6.1-py2.7.egg-info/PKG-INFO
    Skipping file outside of top_level: psutil-0.6.1-py2.7.egg-info/dependency_links.txt
    Skipping file outside of top_level: psutil-0.6.1-py2.7.egg-info/top_level.txt
    '/tmp/tmpYVfs_S/psutil-0.6.1-py2.7-linux-x86_64.egg'

    >>> import sys
    >>> sys.path.append('/tmp/tmpYVfs_S/psutil-0.6.1-py2.7-linux-x86_64.egg')
    >>> import psutil
  """

  NATIVE_EXTENSIONS = frozenset([
        '.pyd',
        '.so',
        '.dylib',
        '.dll'])

  BAD_SYMBOLS = frozenset([
    '__file__'])

  METADATA = 'PEZ-INFO'

  class InvalidDistribution(Exception): pass

  def __init__(self, distribution, debug=False):
    self._debug = debug
    self._dist = distribution
    assert isinstance(self._dist, Distribution)

    if not hasattr(self._dist, 'egg_info') and not self._dist.egg_info:
      raise Distiller.InvalidDistribution('The distribution is missing its egg-info!')
    if not hasattr(self._dist, 'location') and not self._dist.location:
      raise Distiller.InvalidDistribution('The distribution is missing a location!')

    def assert_has_metadata(metadata_txt, message=None):
      if not self._dist.has_metadata(metadata_txt):
        raise Distiller.InvalidDistribution(message or 'Missing %s' % metadata_txt)

    assert_has_metadata('top_level.txt')
    assert_has_metadata('installed-files.txt',
      'This distribution was either created with something other than pip, '
      'twitter.common.python.installer, or is an already-distilled .egg.')

    self._top_levels = self._get_lines('top_level.txt')

    self._installed_files = [
      os.path.realpath(os.path.join(self._dist.egg_info, fn)) for fn in
        self._get_lines('installed-files.txt')]

    self._nspkg = []
    if self._dist.has_metadata('namespace_packages.txt'):
      self._nspkg = self._get_lines('namespace_packages.txt')

  def _log(self, msg):
    if self._debug:
      print(msg, file=sys.stderr)

  def _get_lines(self, txt):
    return list(self._dist.get_metadata_lines(txt))

  def _is_top_level(self, fn):
    rel_fn_base, _ = os.path.splitext(self._relpath(fn))
    return any(rel_fn_base == top_level or rel_fn_base.startswith(top_level + '/')
               for top_level in self._top_levels)

  def _unsafe_source(self):
    not_zip_safe = set()

    for fn in self._installed_files:
      if not self._is_top_level(fn):
        continue
      if not os.path.exists(fn):
        continue
      if not fn.endswith('.py'):
        continue

      with open(fn, 'rb') as fn_fp:
        try:
          parsed_fn = ast.parse(fn_fp.read())
        except SyntaxError as e:
          self._log('WARNING: Syntax error in %s: %s' % (fn, e))
          continue

      # TODO(wickman) This code is considerably more simplistic than the
      # not-zip-safe checker in bdist_egg.  Augment this or keep it conservative?
      for ast_node in ast.walk(parsed_fn):
        if isinstance(ast_node, ast.Name) and ast_node.id in Distiller.BAD_SYMBOLS:
          self._log('WARNING: Detected not-zip-safe code: %s' % fn)
          not_zip_safe.add(fn)
          break
    return not_zip_safe

  def _native_deps(self):
    native_deps = set()
    for fn in self._installed_files:
      if any(fn.endswith(extension) for extension in Distiller.NATIVE_EXTENSIONS):
        native_deps.add(fn)
    return native_deps

  def _package_name(self):
    egg_name = self._dist.egg_name()
    if self._dist.platform and not egg_name.endswith(self._dist.platform):
      egg_name = egg_name + '-' + self._dist.platform
    elif self._native_deps():
      egg_name = egg_name + '-' + get_build_platform()
    return egg_name + '.egg'

  def _relpath(self, fn):
    return os.path.relpath(fn, self._dist.location)

  def _egg_info(self):
    """
      yield (filename, content) pairs of the EGG-INFO directory.
    """

    def egg_info_name(fn):
      return '/'.join(['EGG-INFO', fn])

    def pez_info_name(fn):
      return '/'.join(['PEZ-INFO', fn])

    # .egg-info => EGG-INFO
    # TODO(wickman)  Support .egg files in addition to .egg-info distributions.
    handled_files = frozenset(['native_libs.txt', 'zip-safe', 'not-zip-safe'])
    def skip(fn):
      return any(fn.endswith(filename) for filename in handled_files)

    egg_info_dir = os.path.realpath(self._dist.egg_info)
    for fn in self._installed_files:
      if fn.startswith(egg_info_dir) and not skip(fn):
        rel_fn = os.path.relpath(fn, egg_info_dir)
        if rel_fn == '.': continue
        with open(fn, 'rb') as fp:
          yield egg_info_name(rel_fn), fp.read()

    # dump native_libs.txt
    native_deps = self._native_deps()
    if native_deps:
      yield egg_info_name('native_libs.txt'), '\n'.join(self._relpath(fn) for fn in native_deps)

    # dump zip safety bit
    unsafe_source = self._unsafe_source()
    yield egg_info_name('not-zip-safe' if (unsafe_source or native_deps) else 'zip-safe'), ''
    # if the consumer is a pex, we can be more relaxed about zip-safety.
    yield pez_info_name('not-zip-safe' if unsafe_source else 'zip-safe'), ''

  def distill(self, into=None, strip_pyc=False):
    if not self._top_levels:
      self._log('Installing meta package %s' % self._package_name())
    native_deps = self._native_deps()

    if into is not None:
      safe_mkdir(into)
      filename = os.path.join(into, self._package_name())
    else:
      tempdir = tempfile.mkdtemp()
      filename = os.path.join(tempdir, self._package_name())

    # Filename exists already, assume pre-distilled
    if os.path.exists(filename):
      self._log('Found pre-cached artifact: %s, skipping distillation.' % filename)
      return filename

    with open_zip(filename + '~', 'w', compression=zipfile.ZIP_DEFLATED) as zf:
      for fn in self._installed_files:
        rel_fn = self._relpath(fn)
        if not self._is_top_level(fn):
          self._log('Skipping file outside of top_level: %s' % rel_fn)
          continue
        if not os.path.exists(fn):
          self._log('File does not exist: %s!' % rel_fn)
          continue
        if strip_pyc and (fn.endswith('.pyc') or fn.endswith('.pyo')):
          self._log('Stripping %s' % rel_fn)
          continue

        self._log('Writing %s' % fn)
        zf.write(fn, arcname=rel_fn)
        if fn in native_deps:
          fn_base, extension = os.path.splitext(rel_fn)
          self._log('Writing native stub for %s' % rel_fn)
          zf.writestr(fn_base + '.py', NATIVE_STUB % { 'extension': extension })

      for nspkg in self._nspkg:
        nspkg_init = nspkg.replace('.', '/') + '/__init__.py'
        if nspkg_init in zf.namelist():
          self._log('Cannot write namespace for %s!' % nspkg_init)
        else:
          self._log('Writing namespace package stub for %s' % nspkg)
          zf.writestr(nspkg_init, NAMESPACE_STUB)

      for fn, content in self._egg_info():
        self._log('Writing %s' % fn)
        zf.writestr(fn, content)

    os.rename(filename + '~', filename)
    return filename
