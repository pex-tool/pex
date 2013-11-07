#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
# Copyright 2012 Twitter Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Pure python implementation of zipimport based upon Google AppEngine's
[see http://code.google.com/appengine/articles/django10_zipimport.html]

Modified to allow for nested zip archives, also necessary patches to
pkg_resources (as of distribute 0.6.24) in order to get over bugs in
zipinfo handling.

Usage:
  from twitter.common.python.importer import *
  monkeypatch()
"""
from __future__ import absolute_import

from collections import MappingView, MutableMapping
import contextlib
import os
import sys
import time
import threading
import traceback
import types
import zipfile
import zipimport as builtin_zipimport

from .compatibility import (
    BytesIO,
    PY3,
    exec_function,
)
from .marshaller import CodeMarshaller

StringIO = BytesIO


class ZipDirectoryCache(MutableMapping):
  def __init__(self, shadow):
    self.__shadow = shadow
    self.__lookaside = {}

  def __setitem__(self, key, value):
    try:
      self.__shadow[key] = value
    except TypeError:
      self.__lookaside[key] = value

  def __getitem__(self, key):
    try:
      return self.__shadow[key]
    except KeyError:
      return self.__lookaside[key]

  def __delitem__(self, key):
    try:
      del self.__lookaside[key]
    except KeyError:
      del self.__shadow[key]

  def __iter__(self):
    for key in self.__shadow:
      yield key
    for key in self.__lookaside:
      yield key

  def __len__(self):
    return len(self.__shadow) + len(self.__lookaside)


_zipfile_cache = {}
_zipfile_namecache = {}
_zip_directory_cache = ZipDirectoryCache(builtin_zipimport._zip_directory_cache)


class ZipFileCache(MappingView):
  def __init__(self, archive):
    _zipfile_cache[archive]
    self._archive = archive
    MappingView.__init__(self, _zipfile_cache)

  def keys(self):
    return list(_zipfile_namecache[self._archive])

  def __iter__(self):
    return (zi for zi in _zipfile_namecache[self._archive])

  def __getitem__(self, filename):
    info = _zipfile_cache[self._archive].getinfo(filename.replace(os.sep, '/'))
    dt = info.date_time
    dostime = dt[3] << 11 | dt[4] << 5 | (dt[5] // 2)
    dosdate = (dt[0] - 1980) << 9 | dt[1] << 5 | dt[2]
    return (os.path.join(self._archive, info.filename), info.compress_type,
            info.compress_size, info.file_size, info.header_offset, dostime,
            dosdate, info.CRC)


class Nested(object):
  """
    Helper methods for dealing with mixed/nested file/zip paths.
  """
  # Unfortunately there doesn't seem to be machinery to synthesize IOError(errno=2)
  class FileNotFound(ImportError):
    pass
  class DirectoryNotFound(ImportError):
    pass

  @staticmethod
  def _generate_prefixes(path):
    """
      Iterate the prefixes of a path '/a/b/c/d' => ('/a/b/c/d', '/a/b/c', '/a/b', '/a')
    """
    while path not in ('', '.', os.path.sep):
      yield path
      path, _ = os.path.split(path)

  @staticmethod
  def split_existing(path):
    """
      Split a path by its existing / non-existing components.

      If the path is a file or directory, the non-existing component will be
      '.'
    """
    path = os.path.normpath(path)
    for subpath in Nested._generate_prefixes(path):
      if os.path.lexists(subpath):
        return (subpath, os.path.relpath(path, subpath))
    return (path, '.')

  @staticmethod
  def split_zf_existing(zf, path):
    # TODO(wickman) Cache the zipfile index
    namelist = _zipfile_namecache[zf.filename]
    subpath = os.path.normpath(path)
    while subpath and subpath not in namelist:
      subpath, _ = os.path.split(subpath)
    return (subpath, os.path.relpath(path, subpath))

  @staticmethod
  def open_as(zf, subpath):
    """
      Open a zipfile and synthesize its filename for things that rely upon 'filename'.
    """
    new_zf = zipfile.ZipFile(StringIO(zf.read(subpath)))
    new_zf.filename = os.path.join(zf.filename, subpath)
    return new_zf

  @staticmethod
  def open(path, zf_path=None, zf=None):
    """
      Open potentially nested zip archives.
        path: the path to open, relative to zf (if None, then relative to CWD)
        zf_path: the path to the current zf (if None, then relative to CWD)
        zf: the current zipfile

      Returns (archive, suffix, zipfile)
        archive: the archive name associated with zipfile
        suffix: the leftover path relative to the zipfile archive
        zipfile: the zipfile
    """
    if path == '.':
      assert zf_path is not None
      assert zf is not None
      return (zf_path, '', zf)

    if zf is None:
      existing, non_existing = Nested.split_existing(path)
      next_zf = Nested.get(existing, provider=lambda: zipfile.ZipFile(existing))
      return Nested.open(non_existing, zf_path=existing, zf=next_zf)
    else:
      existing, non_existing = Nested.split_zf_existing(zf, path)
      get_path = os.path.join(zf_path, existing)
      try:
        next_zf = Nested.get(get_path, provider=lambda: Nested.open_as(zf, existing))
        return Nested.open(non_existing, zf_path=get_path, zf=next_zf)
      except (zipfile.BadZipfile, KeyError):
        return (zf_path, path, zf)

  @staticmethod
  def read(path):
    """
      Read the byte contents of a potentially nested file.
    """
    if os.path.isfile(path):
      with open(path, 'rb') as fp:
        return fp.read()

    dirname, basename = os.path.split(path)
    if not basename:
      raise Nested.FileNotFound(path)

    (archive, prefix, zf) = Nested.open(dirname)
    try:
      return zf.read(os.path.join(prefix, basename))
    except KeyError as e:
      raise Nested.FileNotFound(path)

  @staticmethod
  def listdir(path):
    """
      Read the contents of a potentially nested file.
    """
    existing, non_existing = Nested.split_existing(path)
    if non_existing == '.':
      if os.path.isfile(path):
        raise Nested.DirectoryNotFound(path)
      if os.path.isdir(path):
        for p in os.listdir(path):
          yield p
      return

    if os.path.isdir(existing):
      # existing is a directory but there are non_existing components, so listdir is empty
      return

    (archive, prefix, zf) = Nested.open(path)
    namelist = _zipfile_namecache[archive]
    yielded = set()
    for name in namelist:
      if name.startswith(prefix) and name != prefix:
        relpath = os.path.relpath(name, prefix)
        base = relpath.split('/')[0]
        if base not in yielded:
          yield base
          yielded.add(base)

  _ISFILE_CACHE = {}
  @staticmethod
  def isfile(path):
    """
      Read the contents of a potentially nested file.
    """
    hit = Nested._ISFILE_CACHE.get(path, None)
    if hit is not None:
      return hit
    if os.path.isfile(path):
      Nested._ISFILE_CACHE[path] = True
      return True
    dirname, basename = os.path.split(path)
    if not basename:
      Nested._ISFILE_CACHE[path] = False
      return False
    (archive, prefix, zf) = Nested.open(dirname)
    try:
      zf.getinfo(os.path.join(prefix, basename))
      Nested._ISFILE_CACHE[path] = True
      return True
    except KeyError:
      Nested._ISFILE_CACHE[path] = False
      return False

  @staticmethod
  def get(archive, provider=None, zipfile=None):
    """
      Get a cached copy of the archive's zipfile if it's been cached. Otherwise
      create a new zipfile and cache it.

      archive: name of the archive (full path, may or may not be a file)
      provider: a function that can provide a zipfile associated with 'archive' if we need
                to construct one.
      zipfile: the zipfile we're currently using.  if it differs from what is cached,
               close and return the cached copy instead.
    """
    if archive in _zipfile_cache:
      # TODO(wickman)  This is problematic sometimes as the zipfile library has a bug where
      # it assumes the underlying zipfile does not change between reads, so its info cache
      # gets out of date and throws BadZipfile exceptions (e.g. with EGG-INFO/requires.txt)
      if zipfile is not None and _zipfile_cache[archive] != zipfile:
        zipfile.close()
      zf = _zipfile_cache[archive]
    else:
      if zipfile is not None:
        zf = _zipfile_cache[archive] = zipfile
      else:
        assert provider is not None
        zf = _zipfile_cache[archive] = provider()
      _zipfile_namecache[archive] = set(zf.namelist())
    # TODO(wickman)  Do not leave handles open, as this could cause ulimits to
    # be exceeded.
    _zip_directory_cache[archive] = ZipFileCache(archive)
    return zf


@contextlib.contextmanager
def timed(prefix, at_level=1):
  start_time = time.time()
  yield
  end_time = time.time()
  EggZipImporter._log('%s => %.3fms' % (prefix, 1000.0 * (end_time - start_time)), at_level)


# TODO(wickman) Having this be a function (while strictly correct: importers
# only need be callable) seems to break a number of other libraries that try
# to do mro/subclass checking of importers, since issubclass requires a
# class and a function ain't a class.  Make a zipimport proxy class rather
# than a function.
def zipimporter(path):
  try:
    with timed('EggZipImporting %s' % path):
      ezi = EggZipImporter(path)
    return ezi
  except Exception as e:
    with timed('ZipImporting %s' % path, at_level=1):
      bzi = builtin_zipimport.zipimporter(path)
    with EggZipImporter._log_nested("Couldn't EggZipImport %s. " % path, at_level=1):
      for line in traceback.format_exc().splitlines():
        EggZipImporter._log(line, at_level=2)
    return bzi


class EggZipImporter(object):
  """
  A PEP-302 importer that, in addition to zip filenames, also supports:
    - importing from archives within archives
  """
  _LOG_LOCK = threading.Lock()
  _LOG_INDENT = 0

  class ZipImportError(ImportError):
    """Exception raised by zipimporter objects."""

  def __init__(self, path):
    (self.archive, self.prefix, self.zipfile) = Nested.open(path)
    self.prefix = self.prefix + '/' if self.prefix else self.prefix
    self.zipfile = Nested.get(self.archive, zipfile=self.zipfile)

  @classmethod
  def _zipimport_debug_level(cls):
    if 'ZIPIMPORT_DEBUG' not in os.environ:
      return 0
    elif 'ZIPIMPORT_DEBUG' in os.environ:
      try:
        return int(os.environ['ZIPIMPORT_DEBUG'])
      except ValueError:
        return 1

  @classmethod
  def _log(cls, msg, at_level=1):
    if cls._zipimport_debug_level() >= at_level:
      sys.stderr.write('ZIPIMPORT_DEBUG: %s%s\n' % (' '*EggZipImporter._LOG_INDENT, msg))

  @classmethod
  @contextlib.contextmanager
  def _log_nested(cls, msg, at_level=1):
    cls._log(msg, at_level)
    with EggZipImporter._LOG_LOCK:
      EggZipImporter._LOG_INDENT += 2
    yield
    with EggZipImporter._LOG_LOCK:
      EggZipImporter._LOG_INDENT -= 2

  def __repr__(self):
    """Return a string representation matching zipimport.c."""
    name = self.archive
    if self.prefix:
      name = os.path.join(name, self.prefix)
    return '<zipimporter object "%s">' % name

  _SEARCH_ORDER = [
    ('.py', False),
    ('/__init__.py', True),
  ]

  def _get_info(self, fullmodname):
    """Internal helper for find_module() and load_module().

    Args:
      fullmodname: The dot-separated full module name, e.g. 'django.core.mail'.

    Returns:
      A tuple (submodname, is_package, relpath) where:
        submodname: The final component of the module name, e.g. 'mail'.
        is_package: A bool indicating whether this is a package.
        relpath: The path to the module's source code within to the zipfile.

    Raises:
      ImportError if the module is not found in the archive.
    """
    parts = fullmodname.split('.')
    submodname = parts[-1]
    for suffix, is_package in EggZipImporter._SEARCH_ORDER:
      relpath = os.path.join(self.prefix, submodname + suffix.replace('/', os.sep))
      self._log('_get_info(%s) searching relpath:%s, suffix:%s, is_package:%s' % (
        fullmodname, relpath, suffix, is_package), at_level=3)
      self._log('  - is %s a file?' % os.path.join(self.archive, relpath), at_level=3)
      if not Nested.isfile(os.path.join(self.archive, relpath)):
        self._log('    nope', at_level=4)
      else:
        self._log('    yep! submodname: %s, is_package: %s, fullpath: %s' % (
          submodname, is_package, relpath), at_level=4)
        return submodname, is_package, relpath
    msg = ('Can\'t find module %s in zipfile %s with prefix %r' %
           (fullmodname, self.archive, self.prefix))
    self._log(msg, at_level=3)
    raise EggZipImporter.ZipImportError(msg)

  def _get_source(self, fullmodname):
    """Internal helper for load_module().

    Args:
      fullmodname: The dot-separated full module name, e.g. 'django.core.mail'.

    Returns:
      A tuple (submodname, is_package, fullpath, source) where:
        submodname: The final component of the module name, e.g. 'mail'.
        is_package: A bool indicating whether this is a package.
        fullpath: The path to the module's source code including the
          zipfile's filename.
        source: The module's source code.

    Raises:
      ImportError if the module is not found in the archive.
    """
    submodname, is_package, relpath = self._get_info(fullmodname)
    fullpath = '%s%s%s' % (self.archive, os.sep, relpath)
    source = Nested.read(fullpath)
    assert source is not None
    if PY3:
      source = source.decode('utf8')
    source = source.replace('\r\n', '\n').replace('\r', '\n')
    return submodname, is_package, fullpath, source

  def _get_code(self, fullmodname):
    submodname, is_package, relpath = self._get_info(fullmodname)
    relsplit, _ = os.path.split(relpath)
    fullpath = '%s%s%s' % (self.archive, os.sep, relpath)
    pyc = os.path.splitext(fullpath)[0] + '.pyc'
    try:
      with timed('Unmarshaling %s' % pyc, at_level=2):
        pyc_object = CodeMarshaller.from_pyc(BytesIO(Nested.read(pyc)))
    except (Nested.FileNotFound, ValueError, CodeMarshaller.InvalidCode) as e:
      with timed('Compiling %s because of %s' % (fullpath, e.__class__.__name__), at_level=2):
        py = Nested.read(fullpath)
        assert py is not None
        if PY3:
          py = py.decode('utf8')
        pyc_object = CodeMarshaller.from_py(py, fullpath)
    return submodname, is_package, fullpath, pyc_object.code

  def find_module(self, fullmodname, path=None):
    """PEP-302-compliant find_module() method.

    Args:
      fullmodname: The dot-separated full module name, e.g. 'django.core.mail'.
      path: Optional and ignored; present for API compatibility only.

    Returns:
      None if the module isn't found in the archive; self if it is found.
    """
    try:
      submodname, is_package, relpath = self._get_info(fullmodname)
    except ImportError:
      return None
    else:
      return self

  def load_module(self, fullmodname):
    """PEP-302-compliant load_module() method.

    Args:
      fullmodname: The dot-separated full module name, e.g. 'django.core.mail'.

    Returns:
      The module object constructed from the source code.

    Raises:
      SyntaxError if the module's source code is syntactically incorrect.
      ImportError if there was a problem accessing the source code.
      Whatever else can be raised by executing the module's source code.
    """
    with self._log_nested('entering load_module(%s)' % fullmodname, at_level=3):
      submodname, is_package, fullpath, code = self._get_code(fullmodname)
      mod = sys.modules.get(fullmodname)
      try:
        if mod is None:
          mod = sys.modules[fullmodname] = types.ModuleType(fullmodname)
        mod.__loader__ = self
        mod.__file__ = fullpath
        mod.__name__ = fullmodname
        self._log('** __file__ = %s' % mod.__file__, at_level=4)
        self._log('** __name__ = %s' % mod.__name__, at_level=4)
        if is_package:
          mod.__path__ = [os.path.dirname(mod.__file__)]
          self._log('** __path__ = %s' % mod.__path__, at_level=4)
        exec_function(code, mod.__dict__)
      except Exception as e:
        self._log('Caught exception: %s' % e)
        if fullmodname in sys.modules:
          del sys.modules[fullmodname]
        raise
    self._log('exiting load_module(%s) => __file__ = %s, __name__ = %s' % (
      fullmodname, mod.__file__, mod.__name__), at_level=3)
    # We have to do this because of modules like _apipkg that rewrite sys.modules and
    # expect that to be what gets written into the global namespace.
    return sys.modules.get(fullmodname)

  def get_data(self, fullpath):
    """Return (binary) content of a data file in the zipfile."""
    with self._log_nested('entering get_data(archive: %s, path:%s)' % (self.archive, fullpath), at_level=3):
      prefix = os.path.join(self.archive, '')
      if fullpath.startswith(prefix):
        relpath = fullpath[len(prefix):]
      elif os.path.isabs(fullpath):
        raise IOError('Absolute path %r doesn\'t start with zipfile name %r' %
                      (fullpath, prefix))
      else:
        relpath = fullpath
        fullpath = os.path.join(prefix, relpath)

      self._log('nested_read: %s' % fullpath, at_level=4)
      content = Nested.read(fullpath)
      if content is not None:
        self._log('content: %s bytes' % len(content), at_level=4)
        return content
      else:
        self._log('content not found', at_level=4)
        raise IOError('Path %r not found in zipfile %r' % (relpath, self.archive))

  def is_package(self, fullmodname):
    """Return whether a module is a package."""
    with self._log_nested('entering is_package(%s)' % fullmodname, at_level=3):
      submodname, is_package, relpath = self._get_info(fullmodname)
    self._log('exiting is_package(%s) => submodname: %s, is_package: %s, relpath: %s' % (
      fullmodname, submodname, is_package, relpath), at_level=3)
    return is_package

  def get_code(self, fullmodname):
    """Return bytecode for a module."""
    with self._log_nested('entering get_code(%s)' % fullmodname, at_level=3):
      submodname, is_package, fullpath, code = self._get_code(fullmodname)
    self._log('exiting get_code(%s) => submodname: %s, is_package: %s, fullpath: %s' % (
      fullmodname, submodname, is_package, fullpath), at_level=3)
    return code # compile(source, fullpath, 'exec')

  def get_source(self, fullmodname):
    """Return source code for a module."""
    with self._log_nested('entering get_source(%s)' % fullmodname, at_level=3):
      submodname, is_package, fullpath, source = self._get_source(fullmodname)
    self._log('exiting get_source(%s) => submodname: %s, is_package: %s, fullpath: %s, source len: %s' % (
      fullmodname, submodname, is_package, fullpath, len(source)), at_level=3)
    return source


def monkeypatch():
  monkeypatch_zipimport()
  monkeypatch_pkg_resources()


def monkeypatch_zipimport():
  sys.modules['zipimport'] = sys.modules[__name__]

  # PyPy pkgutil still references zipimport._zip_directory_cache directly.
  import pkgutil
  pkgutil.zipimport = sys.modules[__name__]

  from pkgutil import iter_importer_modules, iter_zipimport_modules

  # replace the sys.path_hook for zipimport
  try:
    zi_index = sys.path_hooks.index(builtin_zipimport.zipimporter)
    sys.path_hooks[zi_index] = zipimporter
  except ValueError:
    sys.path_hooks.append(zipimporter)
  path_elements_to_kill = set()

  # flush the path_importer_cache
  for path_element, cached_importer in sys.path_importer_cache.items():
    if isinstance(cached_importer, builtin_zipimport.zipimporter):
      path_elements_to_kill.add(path_element)
  for element in path_elements_to_kill:
    sys.path_importer_cache.pop(element)

  def iter_zipimport_modules_proxy(*args, **kw):
    EggZipImporter._log('Proxying iter_zipimport_modules(%s, %r)' % (
      ', '.join(map(repr, args)), kw), at_level=3)
    for mod in iter_zipimport_modules(*args, **kw):
      EggZipImporter._log('  Yielding => %s' % repr(mod), at_level=4)
      yield mod

  # VOODOO alert: Register the simplegeneric dispatcher for iter_importer_modules
  # Another alternative is to implement EggZipImporter::iter_modules but this is
  # dramatically simpler.
  iter_importer_modules.register(EggZipImporter, iter_zipimport_modules_proxy)


def monkeypatch_pkg_resources():
  """
    There is a bug in pkg_resources ZipProvider, so fix it.
    Filed https://bitbucket.org/tarek/distribute/issue/274
  """
  import pkg_resources
  
  _EggMetadata = pkg_resources.EggMetadata

  def normalized_elements(path):
    path_split = path.split('/')
    while path_split[-1] in ('', '.'):
      path_split.pop(-1)
    return path_split

  class EggMetadata(_EggMetadata):
    def __init__(self, *args, **kw):
      _EggMetadata.__init__(self, *args, **kw)

    def _fn(self, base, resource_name):
      return '/'.join(normalized_elements(_EggMetadata._fn(self, base, resource_name)))

    def _zipinfo_name(self, fspath):
      fspath = normalized_elements(fspath)
      zip_pre = normalized_elements(self.zip_pre)
      if fspath[:len(zip_pre)] == zip_pre:
        return '/'.join(fspath[len(zip_pre):])
      raise AssertionError(
        "%s is not a subpath of %s" % (fspath, self.zip_pre)
      )

  # TODO(wickman) Send pull request to setuptools to allow registering a factory for
  # zipfile.ZipFile
  def build_zipmanifest(path):
    zipinfo = dict()
    def contents_as_zipfile(path):
      new_zf = zipfile.ZipFile(StringIO(Nested.read(path)))
      new_zf.filename = path
      return new_zf
    zfile = contents_as_zipfile(path)
    try:
      for zitem in zfile.namelist():
        zpath = zitem.replace('/', os.sep)
        zipinfo[zpath] = zfile.getinfo(zitem)
        assert zipinfo[zpath] is not None
    finally:
      zfile.close()
    return zipinfo

  pkg_resources.zipimport = sys.modules[__name__]  # if monkeypatching after import
  pkg_resources.build_zipmanifest = build_zipmanifest
  pkg_resources.EggMetadata = EggMetadata
  pkg_resources.register_finder(EggZipImporter, pkg_resources.find_in_zip)
  pkg_resources.register_namespace_handler(EggZipImporter, pkg_resources.file_ns_handler)
  pkg_resources.register_loader_type(EggZipImporter, pkg_resources.ZipProvider)
