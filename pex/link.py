# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import posixpath

from pex.compatibility import WINDOWS, Iterable, pathname2url
from pex.compatibility import string as compatible_string
from pex.compatibility import url2pathname, urlparse
from pex.util import Memoizer


class Link(object):
  """Wrapper around a URL."""

  @classmethod
  def wrap(cls, url):
    """Given a url that is either a string or :class:`Link`, return a :class:`Link`.

    :param url: A string-like or :class:`Link` object to wrap.
    :returns: A :class:`Link` object wrapping the url.
    """
    if isinstance(url, cls):
      return url
    elif isinstance(url, compatible_string):
      return cls(url)
    else:
      raise ValueError('url must be either a string or Link.')

  @classmethod
  def wrap_iterable(cls, url_or_urls):
    """Given a string or :class:`Link` or iterable, return an iterable of :class:`Link` objects.

    :param url_or_urls: A string or :class:`Link` object, or iterable of string or :class:`Link`
      objects.
    :returns: A list of :class:`Link` objects.
    """
    try:
      return [cls.wrap(url_or_urls)]
    except ValueError:
      pass
    if isinstance(url_or_urls, Iterable):
      return [cls.wrap(url) for url in url_or_urls]
    raise ValueError('url_or_urls must be string/Link or iterable of strings/Links')

  @classmethod
  def _normalize(cls, filename):
    return urlparse.urljoin('file:', pathname2url(
        os.path.realpath(os.path.expanduser(filename))))

  # A cache for the result of from_filename
  _FROM_FILENAME_CACHE = Memoizer()

  @classmethod
  def from_filename(cls, filename):
    """Return a :class:`Link` wrapping the local filename."""
    result = cls._FROM_FILENAME_CACHE.get(filename)
    if result is None:
      result = cls(cls._normalize(filename))
      cls._FROM_FILENAME_CACHE.store(filename, result)
    return result

  def __init__(self, url):
    """Construct a :class:`Link` from a url.

    :param url: A string-like object representing a url.
    """
    purl = urlparse.urlparse(url)
    if purl.scheme == '' or (
        WINDOWS and len(purl.scheme) == 1):  # This is likely a drive letter.
      purl = urlparse.urlparse(self._normalize(url))

    self._url = purl

  def __ne__(self, other):
    return not self.__eq__(other)

  def __eq__(self, link):
    return self.__class__ == link.__class__ and self._url == link._url

  def __hash__(self):
    return hash(self._url)

  def join(self, href):
    """Given a href relative to this link, return the :class:`Link` of the absolute url.

    :param href: A string-like path relative to this link.
    """
    return self.wrap(urlparse.urljoin(self.url, href))

  @property
  def filename(self):
    """The basename of this url."""
    return urlparse.unquote(posixpath.basename(self._url.path))

  @property
  def path(self):
    """The full path of this url with any hostname and scheme components removed."""
    return urlparse.unquote(self._url.path)

  @property
  def local_path(self):
    """Returns the local filesystem path (only works for file:// urls)."""
    assert self.local, 'local_path called on a non-file:// url %s' % (self.url,)
    return url2pathname(self.path)

  @property
  def url(self):
    """The url string to which this link points."""
    return urlparse.urlunparse(self._url)

  @property
  def fragment(self):
    """The url fragment following '#' if any."""
    return urlparse.unquote(self._url.fragment)

  @property
  def scheme(self):
    """The URI scheme used by this Link."""
    return self._url.scheme

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
