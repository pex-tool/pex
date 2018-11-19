# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""The finders we wish we had in setuptools.

As of setuptools 3.3, the only finder for zip-based distributions is for eggs.  The path-based
finder only searches paths ending in .egg and not in .whl (zipped or unzipped.)

pex.finders augments pkg_resources with additional finders to achieve functional
parity between wheels and eggs in terms of findability with find_distributions.

To use:
   >>> from pex.finders import register_finders
   >>> register_finders()
"""

from __future__ import absolute_import

import os
import pkgutil
import re
import sys
import zipimport

import pex.third_party.pkg_resources as pkg_resources

if sys.version_info >= (3, 3) and sys.implementation.name == "cpython":
  import importlib.machinery as importlib_machinery
else:
  importlib_machinery = None


class ChainedFinder(object):
  """A utility to chain together multiple pkg_resources finders."""

  @classmethod
  def of(cls, *chained_finder_or_finder):
    finders = []
    for finder in chained_finder_or_finder:
      if isinstance(finder, cls):
        finders.extend(finder.finders)
      else:
        finders.append(finder)
    return cls(finders)

  def __init__(self, finders):
    self.finders = finders

  def __call__(self, importer, path_item, only=False):
    for finder in self.finders:
      for dist in finder(importer, path_item, only=only):
        yield dist

  def __eq__(self, other):
    if not isinstance(other, ChainedFinder):
      return False
    return self.finders == other.finders


# The following methods are somewhat dangerous as pkg_resources._distribution_finders is not an
# exposed API.  As it stands, pkg_resources doesn't provide an API to chain multiple distribution
# finders together.  This is probably possible using importlib but that does us no good as the
# importlib machinery supporting this is only available in Python >= 3.1.
def _get_finder(importer):
  return pkg_resources._distribution_finders.get(importer)


def _add_finder(importer, finder):
  """Register a new pkg_resources path finder that does not replace the existing finder."""

  existing_finder = _get_finder(importer)

  if not existing_finder:
    pkg_resources.register_finder(importer, finder)
  else:
    pkg_resources.register_finder(importer, ChainedFinder.of(existing_finder, finder))


def _remove_finder(importer, finder):
  """Remove an existing finder from pkg_resources."""

  existing_finder = _get_finder(importer)

  if not existing_finder:
    return

  if isinstance(existing_finder, ChainedFinder):
    try:
      existing_finder.finders.remove(finder)
    except ValueError:
      return
    if len(existing_finder.finders) == 1:
      pkg_resources.register_finder(importer, existing_finder.finders[0])
    elif len(existing_finder.finders) == 0:
      pkg_resources.register_finder(importer, pkg_resources.find_nothing)
  else:
    pkg_resources.register_finder(importer, pkg_resources.find_nothing)


class WheelMetadata(pkg_resources.EggMetadata):
  """Metadata provider for zipped wheels."""

  @classmethod
  def _escape(cls, filename_component):
    # See: https://www.python.org/dev/peps/pep-0427/#escaping-and-unicode
    return re.sub("[^\w\d.]+", "_", filename_component, re.UNICODE)

  @classmethod
  def _split_wheelname(cls, wheelname):
    # See: https://www.python.org/dev/peps/pep-0427/#file-name-convention
    assert wheelname.endswith('.whl'), 'invalid wheel name: %s' % wheelname
    split_wheelname = wheelname.rsplit('-', 5)
    assert len(split_wheelname) in (5, 6), 'invalid wheel name: %s' % wheelname
    distribution, version = split_wheelname[:2]
    return '%s-%s' % (distribution, version)

  @classmethod
  def data_dir(cls, wheel_path):
    """Returns the internal path of the data dir for the given wheel.

    As defined https://www.python.org/dev/peps/pep-0427/#the-data-directory

    :rtype: str
    """
    return '%s.data' % cls._split_wheelname(os.path.basename(wheel_path))

  @classmethod
  def dist_info_dir(cls, wheel_path):
    """Returns the internal path of the dist-info dir for the given wheel.

    As defined here: https://www.python.org/dev/peps/pep-0427/#the-dist-info-directory

    :rtype: str
    """
    return '%s.dist-info' % cls._split_wheelname(os.path.basename(wheel_path))

  def _setup_prefix(self):
    path = self.module_path
    old = None
    while path != old:
      if path.lower().endswith('.whl'):
        self.egg_name = os.path.basename(path)
        # TODO(wickman) Test the regression where we have both upper and lower cased package
        # names.
        self.egg_info = os.path.join(path, self.dist_info_dir(self.egg_name))
        self.egg_root = path
        break
      old = path
      path, base = os.path.split(path)


def wheel_from_metadata(location, metadata):
  if not metadata.has_metadata(pkg_resources.DistInfoDistribution.PKG_INFO):
    return None

  from email.parser import Parser
  pkg_info = Parser().parsestr(metadata.get_metadata(pkg_resources.DistInfoDistribution.PKG_INFO))
  return pkg_resources.DistInfoDistribution(
      location=location,
      metadata=metadata,
      # TODO(wickman) Is this necessary or will they get picked up correctly?
      project_name=pkg_info.get('Name'),
      version=pkg_info.get('Version'),
      platform=None)


def find_wheels_on_path(importer, path_item, only=False):
  if not os.path.isdir(path_item) or not os.access(path_item, os.R_OK):
    return
  if not only:
    for entry in os.listdir(path_item):
      if entry.lower().endswith('.whl'):
        for dist in pkg_resources.find_distributions(os.path.join(path_item, entry)):
          yield dist


def find_wheels_in_zip(importer, path_item, only=False):
  metadata = WheelMetadata(importer)
  dist = wheel_from_metadata(path_item, metadata)
  if dist:
    yield dist


__PREVIOUS_FINDER = None


def register_finders():
  """Register finders necessary for PEX to function properly."""

  # If the previous finder is set, then we've already monkeypatched, so skip.
  global __PREVIOUS_FINDER
  if __PREVIOUS_FINDER:
    return

  # save previous finder so that it can be restored
  previous_finder = _get_finder(zipimport.zipimporter)
  assert previous_finder, 'This appears to be using an incompatible setuptools.'

  # Enable finding zipped wheels.
  pkg_resources.register_finder(
      zipimport.zipimporter, ChainedFinder.of(pkg_resources.find_eggs_in_zip, find_wheels_in_zip))

  # append the wheel finder
  _add_finder(pkgutil.ImpImporter, find_wheels_on_path)

  if importlib_machinery is not None:
    _add_finder(importlib_machinery.FileFinder, find_wheels_on_path)

  __PREVIOUS_FINDER = previous_finder


def unregister_finders():
  """Unregister finders necessary for PEX to function properly."""

  global __PREVIOUS_FINDER
  if not __PREVIOUS_FINDER:
    return

  pkg_resources.register_finder(zipimport.zipimporter, __PREVIOUS_FINDER)
  _remove_finder(pkgutil.ImpImporter, find_wheels_on_path)

  if importlib_machinery is not None:
    _remove_finder(importlib_machinery.FileFinder, find_wheels_on_path)

  __PREVIOUS_FINDER = None


def get_script_from_egg(name, dist):
  """Returns location, content of script in distribution or (None, None) if not there."""
  if dist.metadata_isdir('scripts') and name in dist.metadata_listdir('scripts'):
    return (
        os.path.join(dist.egg_info, 'scripts', name),
        dist.get_metadata('scripts/%s' % name).replace('\r\n', '\n').replace('\r', '\n'))
  return None, None


def get_script_from_whl(name, dist):
  # This can get called in different contexts; in some, it looks for files in the
  # wheel archives being used to produce a pex; in others, it looks for files in the
  # install wheel directory included in the pex. So we need to look at both locations.
  datadir_name = WheelMetadata.data_dir(dist.location)
  wheel_scripts_dirs = ['bin', 'scripts',
                         os.path.join(datadir_name, "bin"),
                         os.path.join(datadir_name, "scripts")]
  for wheel_scripts_dir in wheel_scripts_dirs:
    if (dist.resource_isdir(wheel_scripts_dir) and
        name in dist.resource_listdir(wheel_scripts_dir)):
      # We always install wheel scripts into bin
      script_path = os.path.join(wheel_scripts_dir, name)
      return (
          os.path.join(dist.location, script_path),
          dist.get_resource_string('', script_path).replace(b'\r\n', b'\n').replace(b'\r', b'\n'))
  return None, None


def get_script_from_distribution(name, dist):
  # PathMetadata: exploded distribution on disk.
  if isinstance(dist._provider, pkg_resources.PathMetadata):
    if dist.egg_info.endswith('EGG-INFO'):
      return get_script_from_egg(name, dist)
    elif dist.egg_info.endswith('.dist-info'):
      return get_script_from_whl(name, dist)
    else:
      return None, None
  # WheelMetadata: Zipped whl (in theory should not experience this at runtime.)
  elif isinstance(dist._provider, WheelMetadata):
    return get_script_from_whl(name, dist)
  # EggMetadata: Zipped egg
  elif isinstance(dist._provider, pkg_resources.EggMetadata):
    return get_script_from_egg(name, dist)
  return None, None


def get_script_from_distributions(name, dists):
  for dist in dists:
    script_path, script_content = get_script_from_distribution(name, dist)
    if script_path:
      return dist, script_path, script_content
  return None, None, None


def get_entry_point_from_console_script(script, dists):
  # Check all distributions for the console_script "script". De-dup by dist key to allow for a
  # duplicate console script IFF the distribution is platform-specific and this is a multi-platform
  # pex.
  def get_entrypoint(dist):
    script_entry = dist.get_entry_map().get('console_scripts', {}).get(script)
    if script_entry is not None:
      # Entry points are of the form 'foo = bar', we just want the 'bar' part.
      return str(script_entry).split('=')[1].strip()

  entries = {}
  for dist in dists:
    entry_point = get_entrypoint(dist)
    if entry_point is not None:
      entries[dist.key] = (dist, entry_point)

  if len(entries) > 1:
    raise RuntimeError(
        'Ambiguous script specification %s matches multiple entry points:\n\t%s' % (
            script,
            '\n\t'.join('%r from %r' % (entry_point, dist)
                        for dist, entry_point in entries.values())))

  dist, entry_point = None, None
  if entries:
    dist, entry_point = next(iter(entries.values()))
  return dist, entry_point
