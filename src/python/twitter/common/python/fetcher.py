from abc import abstractmethod
import itertools
import random

from twitter.common.dirutil import safe_mkdir, safe_mkdtemp
from twitter.common.lang import AbstractClass

from .base import maybe_requirement
from .http import Crawler, SourceLink
from .translator import SourceTranslator, EggTranslator

from pkg_resources import Requirement

from twitter.common.lang import Compatibility


if Compatibility.PY3:
  import urllib.parse as urlparse
else:
  import urlparse


class FetcherBase(AbstractClass):
  """
    A fetcher takes a Requirement and tells us where to crawl to find it.
  """
  @abstractmethod
  def urls(self, req):
    raise NotImplementedError


class Fetcher(FetcherBase):
  def __init__(self, urls):
    # TODO(wickman) self.urls = maybe_list(urls)
    self._urls = urls

  def urls(self, _):
    return self._urls


class PyPIFetcher(FetcherBase):
  PYPI_BASE = 'pypi.python.org'

  @classmethod
  def resolve_mirrors(cls, base):
    """Resolve mirrors per PEP-0381."""
    import socket
    def crange(ch1, ch2):
      return [chr(ch) for ch in range(ord(ch1), ord(ch2) + 1)]
    last, _, _ = socket.gethostbyname_ex('last.' + base)
    assert last.endswith(base)
    last_prefix = last.split('.')[0]
    # TODO(wickman) Is implementing > z really necessary?
    last_prefix = 'z' if len(last_prefix) > 1 else last_prefix[0]
    return ['%c.%s' % (letter, base) for letter in crange('a', last_prefix)]

  def __init__(self, pypi_base=PYPI_BASE, use_mirrors=False):
    parts = urlparse.urlparse(pypi_base)
    self.scheme, host = (parts.scheme, parts.netloc) if parts.scheme else ('http', pypi_base)
    self.mirrors = self.resolve_mirrors(host) if use_mirrors else [host]

  def urls(self, req):
    req = maybe_requirement(req)
    random_mirror = random.choice(self.mirrors)
    return ['%s://%s/simple/%s/' % (self.scheme, random_mirror, req.project_name)]
