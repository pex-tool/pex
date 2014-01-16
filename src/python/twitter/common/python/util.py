from __future__ import absolute_import

import contextlib
import errno
from hashlib import sha1
import os
import shutil
import uuid

from .common import safe_open, safe_rmtree

from pkg_resources import (
    Distribution,
    EggMetadata,
    PathMetadata,
    find_distributions,
)


class DistributionHelper(object):
  @staticmethod
  def walk_data(dist, path='/'):
    """Yields filename, stream for files identified as data in the distribution"""
    for rel_fn in filter(None, dist.resource_listdir(path)):
      full_fn = os.path.join(path, rel_fn)
      if dist.resource_isdir(full_fn):
        for fn, stream in DistributionHelper.walk_data(dist, full_fn):
          yield fn, stream
      else:
        yield full_fn[1:], dist.get_resource_stream(dist._provider, full_fn)

  @staticmethod
  def zipsafe(dist):
    """Returns whether or not we determine a distribution is zip-safe.

       Only works for egg distributions."""
    try:
      pez_info = dist.resource_listdir('/PEZ-INFO')
    except OSError:
      pez_info = []
    if 'zip-safe' in pez_info:
      return True
    egg_metadata = dist.metadata_listdir('/')
    return 'zip-safe' in egg_metadata and 'native_libs.txt' not in egg_metadata

  @classmethod
  def distribution_from_path(cls, location, location_base=None):
    """Returns a Distribution given a location.

       If the distribution name should be based off a different egg name than
       described by the location, supply location_base as an alternate name, e.g.
       DistributionHelper.distribution_from_path('/path/to/wrong_package_name-3.2.1',
           'right_package_name-1.2.3.egg')
    """
    location_base = location_base or os.path.basename(location)
    if os.path.isdir(location):
      metadata = PathMetadata(location, os.path.join(location, 'EGG-INFO'))
    else:
      from zipimport import zipimporter
      metadata = EggMetadata(zipimporter(location))
    return Distribution.from_location(location, location_base, metadata=metadata)


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
    digest.update(''.join(names).encode('utf-8'))
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
    normpath = os.path.normpath(directory)
    for root, _, files in os.walk(normpath):
      for f in files:
        yield os.path.relpath(os.path.join(root, f), normpath)

  @classmethod
  def pex_hash(cls, d):
    """Return a reproducible hash of the contents of a directory."""
    names = sorted(f for f in cls._iter_files(d) if not (f.endswith('.pyc') or f.startswith('.')))
    def stream_factory(name):
      return open(os.path.join(d, name), 'rb')
    return cls._compute_hash(names, stream_factory)

  @classmethod
  def dir_hash(cls, d):
    """Return a reproducible hash of the contents of a directory."""
    names = sorted(f for f in cls._iter_files(d) if not f.endswith('.pyc'))
    def stream_factory(name):
      return open(os.path.join(d, name), 'rb')
    return cls._compute_hash(names, stream_factory)

  @classmethod
  def cache_distribution(cls, zf, source, target_dir):
    """Possibly cache an egg from within a zipfile into target_cache.

       Given a zipfile handle and a filename corresponding to an egg distribution within
       that zip, maybe write to the target cache and return a Distribution."""
    dependency_basename = os.path.basename(source)
    if not os.path.exists(target_dir):
      target_dir_tmp = target_dir + '.' + uuid.uuid4().hex
      for name in zf.namelist():
        if name.startswith(source) and not name.endswith('/'):
          # strip off prefix + '/'
          target_name = os.path.join(dependency_basename, name[len(source) + 1:])
          with contextlib.closing(zf.open(name)) as zi:
            with safe_open(os.path.join(target_dir_tmp, target_name), 'wb') as fp:
              shutil.copyfileobj(zi, fp)
      try:
        os.rename(target_dir_tmp, target_dir)
      except OSError as e:
        if e.errno == errno.ENOTEMPTY:
          safe_rmtree(target_dir_tmp)
        else:
          raise
    distributions = list(find_distributions(target_dir))
    assert len(distributions) == 1, 'Failed to cache distribution %s' % source
    return distributions[0]
