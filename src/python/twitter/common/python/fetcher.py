from __future__ import absolute_import

from abc import abstractmethod
import random
import warnings

from .base import maybe_requirement
from .compatibility import AbstractClass, PY3

if PY3:
  import urllib.parse as urlparse
  from urllib.parse import urljoin
else:
  import urlparse
  from urlparse import urljoin


class FetcherBase(AbstractClass):
  """
    A fetcher takes a Requirement and tells us where to crawl to find it.
  """
  @abstractmethod
  def urls(self, req):
    raise NotImplementedError


class Fetcher(FetcherBase):
  def __init__(self, urls):
    self._urls = urls

  def urls(self, _):
    return self._urls


class PyPIFetcher(FetcherBase):
  PYPI_BASE = 'https://pypi.python.org'

  def __init__(self, pypi_base=PYPI_BASE, use_mirrors=False):
    if use_mirrors:
      warnings.warn('use_mirrors is now deprecated.')

    pypi_url = urlparse.urlparse(pypi_base)
    if not pypi_url.scheme:
      self.__pypi_base = 'http://' + pypi_base
    else:
      self.__pypi_base = pypi_base

  def urls(self, req):
    req = maybe_requirement(req)
    return [urljoin(self.__pypi_base, 'simple/%s/' % req.project_name)]
