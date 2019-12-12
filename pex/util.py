# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import contextlib
import os
import tempfile
from hashlib import sha1
from site import makepath

from pex.common import atomic_directory, safe_mkdir, safe_mkdtemp
from pex.compatibility import exec_function
from pex.third_party.pkg_resources import (
    find_distributions,
    resource_isdir,
    resource_listdir,
    resource_string
)
from pex.tracer import TRACER


class DistributionHelper(object):
  @classmethod
  def walk_data(cls, dist, path='/'):
    """Yields filename, stream for files identified as data in the distribution"""
    for rel_fn in filter(None, dist.resource_listdir(path)):
      full_fn = os.path.join(path, rel_fn)
      if dist.resource_isdir(full_fn):
        for fn, stream in cls.walk_data(dist, full_fn):
          yield fn, stream
      else:
        yield full_fn[1:], dist.get_resource_stream(dist._provider, full_fn)

  @classmethod
  def access_zipped_assets(cls, static_module_name, static_path, dir_location=None):
    """
    Create a copy of static resource files as we can't serve them from within the pex file.

    :param static_module_name: Module name containing module to cache in a tempdir
    :type static_module_name: string, for example 'twitter.common.zookeeper' or similar
    :param static_path: Module name, for example 'serverset'
    :param dir_location: create a new temporary directory inside, or None to have one created
    :returns temp_dir: Temporary directory with the zipped assets inside
    :rtype: str
    """

    # asset_path is initially a module name that's the same as the static_path, but will be
    # changed to walk the directory tree
    def walk_zipped_assets(static_module_name, static_path, asset_path, temp_dir):
      for asset in resource_listdir(static_module_name, asset_path):
        asset_target = os.path.normpath(
            os.path.join(os.path.relpath(asset_path, static_path), asset))
        if resource_isdir(static_module_name, os.path.join(asset_path, asset)):
          safe_mkdir(os.path.join(temp_dir, asset_target))
          walk_zipped_assets(static_module_name, static_path, os.path.join(asset_path, asset),
            temp_dir)
        else:
          with open(os.path.join(temp_dir, asset_target), 'wb') as fp:
            path = os.path.join(static_path, asset_target)
            file_data = resource_string(static_module_name, path)
            fp.write(file_data)

    if dir_location is None:
      temp_dir = safe_mkdtemp()
    else:
      temp_dir = dir_location

    walk_zipped_assets(static_module_name, static_path, static_path, temp_dir)

    return temp_dir

  @classmethod
  def distribution_from_path(cls, path, name=None):
    """Return a distribution from a path.

    If name is provided, find the distribution.  If none is found matching the name,
    return None.  If name is not provided and there is unambiguously a single
    distribution, return that distribution otherwise None.
    """
    if name is None:
      distributions = set(find_distributions(path))
      if len(distributions) == 1:
        return distributions.pop()
    else:
      for dist in find_distributions(path):
        if dist.project_name == name:
          return dist


class CacheHelper(object):
  @classmethod
  def update_hash(cls, filelike, digest):
    """Update the digest of a single file in a memory-efficient manner."""
    block_size = digest.block_size * 1024
    for chunk in iter(lambda: filelike.read(block_size), b''):
      digest.update(chunk)

  @classmethod
  def hash(cls, path, digest=None, hasher=sha1):
    """Return the digest of a single file in a memory-efficient manner."""
    if digest is None:
      digest = hasher()
    with open(path, 'rb') as fh:
      cls.update_hash(fh, digest)
    return digest.hexdigest()

  @classmethod
  def _compute_hash(cls, names, stream_factory):
    digest = sha1()
    # Always use / as the path separator, since that's what zip uses.
    hashed_names = [n.replace(os.sep, '/') for n in names]
    digest.update(''.join(hashed_names).encode('utf-8'))
    for name in names:
      with contextlib.closing(stream_factory(name)) as fp:
        cls.update_hash(fp, digest)
    return digest.hexdigest()

  @classmethod
  def zip_hash(cls, zf, prefix=''):
    """Return the hash of the contents of a zipfile, comparable with a cls.dir_hash."""
    prefix_length = len(prefix)
    names = sorted(name[prefix_length:] for name in zf.namelist()
        if name.startswith(prefix) and not name.endswith('.pyc') and not name.endswith('/'))
    def stream_factory(name):
      return zf.open(prefix + name)
    return cls._compute_hash(names, stream_factory)

  @classmethod
  def _iter_files(cls, directory):
    normpath = os.path.realpath(os.path.normpath(directory))
    for root, _, files in os.walk(normpath):
      for f in files:
        yield os.path.relpath(os.path.join(root, f), normpath)

  @classmethod
  def pex_hash(cls, d):
    """Return a reproducible hash of the contents of a directory."""
    names = sorted(f for f in cls._iter_files(d) if not (f.endswith('.pyc') or f.startswith('.')))
    def stream_factory(name):
      return open(os.path.join(d, name), 'rb')  # noqa: T802
    return cls._compute_hash(names, stream_factory)

  @classmethod
  def dir_hash(cls, d):
    """Return a reproducible hash of the contents of a directory."""
    names = sorted(f for f in cls._iter_files(d) if not f.endswith('.pyc'))
    def stream_factory(name):
      return open(os.path.join(d, name), 'rb')  # noqa: T802
    return cls._compute_hash(names, stream_factory)

  @classmethod
  def cache_distribution(cls, zf, source, target_dir):
    """Possibly cache a wheel from within a zipfile into `target_dir`.

    Given a zipfile handle and a source path prefix corresponding to a wheel install embedded within
    that zip, maybe extract the wheel install into the target cache and then return a distribution
    from the cache.

    :param zf: An open zip file (a zipped pex).
    :type zf: :class:`zipfile.ZipFile`
    :param str source: The path prefix of a wheel install embedded in the zip file.
    :param str target_dir: The directory to cache the distribution in if not already cached.
    :returns: The cached distribution.
    :rtype: :class:`pex.third_party.pkg_resources.Distribution`
    """
    with atomic_directory(target_dir, source=source) as target_dir_tmp:
      if target_dir_tmp is None:
        TRACER.log('Using cached {}'.format(target_dir))
      else:
        with TRACER.timed('Caching {}:{} in {}'.format(zf.filename, source, target_dir)):
          for name in zf.namelist():
            if name.startswith(source) and not name.endswith('/'):
              zf.extract(name, target_dir_tmp)

    dist = DistributionHelper.distribution_from_path(target_dir)
    assert dist is not None, 'Failed to cache distribution '.format(source)
    return dist


@contextlib.contextmanager
def named_temporary_file(*args, **kwargs):
  """
  Due to a bug in python (https://bugs.python.org/issue14243), we need
  this to be able to use the temporary file without deleting it.
  """
  assert 'delete' not in kwargs
  kwargs['delete'] = False
  fp = tempfile.NamedTemporaryFile(*args, **kwargs)
  try:
    with fp:
      yield fp
  finally:
    os.remove(fp.name)


def iter_pth_paths(filename):
  """Given a .pth file, extract and yield all inner paths without honoring imports. This shadows
  python's site.py behavior, which is invoked at interpreter startup."""
  try:
    f = open(filename, 'rU')  # noqa
  except IOError:
    return

  dirname = os.path.dirname(filename)
  known_paths = set()

  with f:
    for line in f:
      line = line.rstrip()
      if not line or line.startswith('#'):
        continue
      elif line.startswith(('import ', 'import\t')):
        try:
          exec_function(line, globals_map={})
          continue
        except Exception:
          # NB: import lines are routinely abused with extra code appended using `;` so the class of
          # exceptions that might be raised in broader than ImportError. As such we cacth broadly
          # here.

          # Defer error handling to the higher level site.py logic invoked at startup.
          return
      else:
        extras_dir, extras_dir_case_insensitive = makepath(dirname, line)
        if extras_dir_case_insensitive not in known_paths and os.path.exists(extras_dir):
          yield extras_dir
          known_paths.add(extras_dir_case_insensitive)
