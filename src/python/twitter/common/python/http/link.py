from __future__ import absolute_import

import contextlib
import os
import posixpath
import tarfile
import zipfile

from ..base import maybe_requirement
from ..common import safe_mkdir, safe_mkdtemp
from ..compatibility import PY3

from pkg_resources import (
    Distribution,
    EGG_NAME,
    parse_version,
    Requirement,
    safe_name,
)

if PY3:
  import urllib.parse as urlparse
else:
  import urlparse


class Link(object):
  """An HTTP link."""

  class Error(Exception): pass
  class InvalidLink(Error): pass
  class UnreadableLink(Error): pass

  def __init__(self, url, opener=None):
    self._url = urlparse.urlparse(url)
    self._opener = opener

  def __eq__(self, link):
    return self.__class__ == link.__class__ and self._url == link._url

  @property
  def filename(self):
    return posixpath.basename(self._url.path)

  @property
  def url(self):
    return urlparse.urlunparse(self._url)

  @property
  def local(self):
    """Is the url a local file?"""
    return self._url.scheme in ('', 'file')

  @property
  def remote(self):
    """Is the url a remote file?"""
    return self._url.scheme in ('http', 'https')

  def __repr__(self):
    return '%s(%r)' % (self.__class__.__name__, self.url)

  def fh(self, conn_timeout=None):
    if not self._opener:
      raise self.UnreadableLink("Link cannot be read: no opener supplied.")
    return self._opener.open(self.url, conn_timeout=conn_timeout)

  def fetch(self, location=None, conn_timeout=None):
    if self.local and location is None:
      return self._url.path
    location = location or safe_mkdtemp()
    target = os.path.join(location, self.filename)
    if os.path.exists(target):
      return target
    with contextlib.closing(self.fh(conn_timeout=conn_timeout)) as url_fp:
      safe_mkdir(os.path.dirname(target))
      with open(target, 'wb') as fp:
        fp.write(url_fp.read())
    return target


class ExtendedLink(Link):
  @property
  def name(self):
    return NotImplementedError

  @property
  def version(self):
    return parse_version(self.raw_version)

  @property
  def raw_version(self):
    return NotImplementedError

  @property
  def py_version(self):
    return None

  @property
  def platform(self):
    return None

  def satisfies(self, requirement):
    """Does the signature of this filename match the requirement (pkg_resources.Requirement)?"""
    requirement = maybe_requirement(requirement)
    distribution = Distribution(project_name=self.name, version=self.raw_version,
      py_version=self.py_version, platform=self.platform)
    if distribution.key != requirement.key:
      return False
    return self.raw_version in requirement


class SourceLink(ExtendedLink):
  """A Target providing source that can be built into a Distribution via Installer."""

  EXTENSIONS = {
    '.tar': (tarfile.TarFile.open, tarfile.ReadError),
    '.tar.gz': (tarfile.TarFile.open, tarfile.ReadError),
    '.tar.bz2': (tarfile.TarFile.open, tarfile.ReadError),
    '.tgz': (tarfile.TarFile.open, tarfile.ReadError),
    '.zip': (zipfile.ZipFile, zipfile.BadZipfile)
  }

  @classmethod
  def split_fragment(cls, fragment):
    """heuristic to split by version name/fragment:

       >>> split_fragment('pysolr-2.1.0-beta')
       ('pysolr', '2.1.0-beta')
       >>> split_fragment('cElementTree-1.0.5-20051216')
       ('cElementTree', '1.0.5-20051216')
       >>> split_fragment('pil-1.1.7b1-20090412')
       ('pil', '1.1.7b1-20090412')
       >>> split_fragment('django-plugin-2-2.3')
       ('django-plugin-2', '2.3')
    """
    def likely_version_component(enumerated_fragment):
      return sum(bool(v and v[0].isdigit()) for v in enumerated_fragment[1].split('.'))
    fragments = fragment.split('-')
    if len(fragments) == 1:
      return fragment, ''
    max_index, _ = max(enumerate(fragments), key=likely_version_component)
    return '-'.join(fragments[0:max_index]), '-'.join(fragments[max_index:])

  def __init__(self, url, **kw):
    super(SourceLink, self).__init__(url, **kw)

    for ext, class_info in self.EXTENSIONS.items():
      if self.filename.endswith(ext):
        self._archive_class = class_info
        fragment = self.filename[:-len(ext)]
        break
    else:
      raise self.InvalidLink('%s does not end with any of: %s' % (
          self.filename, ' '.join(self.EXTENSIONS)))
    self._name, self._raw_version = self.split_fragment(fragment)

  @property
  def name(self):
    return safe_name(self._name)

  @property
  def raw_version(self):
    return safe_name(self._raw_version)

  @staticmethod
  def first_nontrivial_dir(path):
    files = os.listdir(path)
    if len(files) == 1 and os.path.isdir(os.path.join(path, files[0])):
      return SourceLink.first_nontrivial_dir(os.path.join(path, files[0]))
    else:
      return path

  def _unpack(self, filename, location=None):
    """Unpack this source target into the path if supplied.  If the path is not supplied, a
       temporary directory will be created."""
    path = location or safe_mkdtemp()
    archive_class, error_class = self._archive_class
    try:
      with contextlib.closing(archive_class(filename)) as package:
        package.extractall(path=path)
    except error_class:
      raise self.UnreadableLink('Could not read %s' % self.url)
    return self.first_nontrivial_dir(path)

  def fetch(self, location=None, conn_timeout=None):
    target = super(SourceLink, self).fetch(conn_timeout=conn_timeout)
    return self._unpack(target, location)


class EggLink(ExtendedLink):
  """A Target providing an egg."""

  def __init__(self, url, **kw):
    super(EggLink, self).__init__(url, **kw)
    filename, ext = os.path.splitext(self.filename)
    if ext.lower() != '.egg':
      raise self.InvalidLink('Not an egg: %s' % filename)
    matcher = EGG_NAME(filename)
    if not matcher:
      raise self.InvalidLink('Could not match egg: %s' % filename)
    self._name, self._raw_version, self._py_version, self._platform = matcher.group(
        'name', 'ver', 'pyver', 'plat')

  def __hash__(self):
    return hash((self.name, self.version, self.py_version, self.platform))

  @property
  def name(self):
    return safe_name(self._name)

  @property
  def raw_version(self):
    return safe_name(self._raw_version)

  @property
  def py_version(self):
    return self._py_version

  @property
  def platform(self):
    return self._platform
