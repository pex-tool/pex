from __future__ import absolute_import

import errno
import os
import shutil
import sys
import tempfile

from .common import safe_rmtree, safe_open, safe_mkdir
from .compatibility import BytesIO

from pkg_resources import find_distributions, PathMetadata, Distribution


class DistributionHelper(object):
  @staticmethod
  def walk_metadata(dist, path='/'):
    """yields filename, content for files identified as metadata in the distribution"""
    for rel_fn in filter(None, dist.metadata_listdir(path)):
      full_fn = os.path.join(path, rel_fn)
      if dist.metadata_isdir(full_fn):
        for fn, content in DistributionHelper.walk_metadata(dist, full_fn):
          yield fn, content
      else:
        yield os.path.join('EGG-INFO', full_fn[1:]), dist.get_metadata(full_fn).encode('utf-8')

  @staticmethod
  def walk_data(dist, path='/'):
    """yields filename, stream for files identified as data in the distribution"""
    for rel_fn in filter(None, dist.resource_listdir(path)):
      full_fn = os.path.join(path, rel_fn)
      if dist.resource_isdir(full_fn):
        for fn, stream in DistributionHelper.walk_data(dist, full_fn):
          yield fn, stream
      else:
        yield full_fn[1:], dist.get_resource_stream(dist._provider, full_fn)

  @staticmethod
  def walk(dist):
    """yields filename, stream for all files in the distribution"""
    for fn, content in DistributionHelper.walk_metadata(dist):
      yield fn, BytesIO(content)
    for fn, content in DistributionHelper.walk_data(dist):
      yield fn, content

  @staticmethod
  def maybe_locally_cache(dist, cache_dir):
    egg_name = os.path.join(cache_dir, dist.egg_name() + '.egg')
    safe_mkdir(cache_dir)
    if not os.path.exists(egg_name):
      egg_tmp_path = tempfile.mkdtemp(dir=cache_dir, prefix=dist.egg_name())
      for fn, stream in DistributionHelper.walk(dist):
        with safe_open(os.path.join(egg_tmp_path, fn), 'wb') as fp:
          shutil.copyfileobj(stream, fp)
      try:
        os.rename(egg_tmp_path, egg_name)
      except OSError as e:
        # Handle the race condition of other people trying to write into the target cache.
        if e.errno == errno.ENOTEMPTY:
          safe_rmtree(egg_tmp_path)
    metadata = PathMetadata(egg_name, os.path.join(egg_name, 'EGG-INFO'))
    return Distribution.from_filename(egg_name, metadata=metadata)

  @staticmethod
  def all_distributions(path=sys.path):
    for element in path:
      for dist in find_distributions(element):
        yield dist
