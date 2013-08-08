import errno
import os
import sys
import tempfile

class DistributionHelper(object):
  @staticmethod
  def walk_metadata(dist, path='/'):
    for rel_fn in filter(None, dist.metadata_listdir(path)):
      full_fn = os.path.join(path, rel_fn)
      if dist.metadata_isdir(full_fn):
        for fn, content in DistributionHelper.walk_metadata(dist, full_fn):
          yield fn, content
      else:
        yield os.path.join('EGG-INFO', full_fn[1:]), dist.get_metadata(full_fn)

  @staticmethod
  def walk_data(dist, path='/'):
    for rel_fn in filter(None, dist.resource_listdir(path)):
      full_fn = os.path.join(path, rel_fn)
      if dist.resource_isdir(full_fn):
        for fn, content in DistributionHelper.walk_data(dist, full_fn):
          yield fn, content
      else:
        yield full_fn[1:], dist.get_resource_string(dist._provider, full_fn)

  @staticmethod
  def walk(dist):
    for fn, content in DistributionHelper.walk_metadata(dist):
      yield fn, content
    for fn, content in DistributionHelper.walk_data(dist):
      yield fn, content

  @staticmethod
  def maybe_locally_cache(dist, cache_dir):
    from pkg_resources import PathMetadata, Distribution
    from twitter.common.dirutil import safe_rmtree, safe_open, safe_mkdir
    egg_name = os.path.join(cache_dir, dist.egg_name() + '.egg')
    safe_mkdir(cache_dir)
    if not os.path.exists(egg_name):
      egg_tmp_path = tempfile.mkdtemp(dir=cache_dir, prefix=dist.egg_name())
      for fn, content in DistributionHelper.walk(dist):
        with safe_open(os.path.join(egg_tmp_path, fn), 'wb') as fp:
          fp.write(content)
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
    from pkg_resources import find_distributions
    for element in path:
      for dist in find_distributions(element):
        yield dist
