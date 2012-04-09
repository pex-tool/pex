import os
import tempfile
import time
try:
  from urllib2 import HTTPError
except ImportError:
  from urllib.error import HTTPError

from pip.download import unpack_http_url
from pip.exceptions import DistributionNotFound
from pip.index import PackageFinder
from pip.req import InstallRequirement

from twitter.common.dirutil import safe_rmtree, safe_mkdir

class Fetcher(object):
  """
    A requirement downloader.

    Simple example:
      >>> from twitter.common.python.installer import Fetcher
      >>> pypi = Fetcher.pypi()     # create a basic Fetcher that points to pypi
      >>> pypi.fetch('django-celery>2.4')
      '/var/folders/Uh/UhXpeRIeFfGF7HoogOKC+++++TI/-Tmp-/tmpDKeKEv'
      >>> os.listdir('/var/folders/Uh/UhXpeRIeFfGF7HoogOKC+++++TI/-Tmp-/tmpDKeKEv')
      ['AUTHORS', 'bin', 'Changelog', 'contrib', 'django_celery.egg-info',
      'djcelery', 'docs', 'examples', 'FAQ', 'INSTALL', 'LICENSE', 'locale',
      'MANIFEST.in', 'PKG-INFO', 'README', 'README.rst', 'requirements',
      'setup.cfg', 'setup.py', 'tests', 'THANKS', 'TODO']

    This directory can then be passed into the Installer, which builds distributions, which
    can then be passed to the distiller in order to distill .eggs.
  """
  MAX_RETRIES = 5

  @classmethod
  def pypi(cls):
    return cls([], external=True)

  def __init__(self, repositories, indices=(), external=False, download_cache=None):
    self._cleanup = download_cache is None
    self._cache = download_cache or tempfile.mkdtemp()
    if not os.path.exists(self._cache):
      safe_mkdir(self._cache)
    self._use_mirrors = external
    self._repositories = list(repositories)
    self._indices = list(indices)
    self._reinit()

  def _reinit(self):
    self._finder = PackageFinder(self._repositories, self._indices, use_mirrors=self._use_mirrors)

  def __del__(self):
    if self._cleanup:
      safe_rmtree(self._cache)

  def fetch(self, requirement):
    """
      Fetch a requirement and unpack it into a temporary directory.

      The responsibility of cleaning up the temporary directory returned is
      that of the caller.
    """
    download_tmp = tempfile.mkdtemp()

    for _ in range(Fetcher.MAX_RETRIES):
      ir = InstallRequirement.from_line(str(requirement))
      try:
        try:
          ir_link = self._finder.find_requirement(ir, upgrade=True)
        except DistributionNotFound:
          return None
        unpack_http_url(ir_link, download_tmp, self._cache)
        return download_tmp
      # This is distinctly below average because it means I need to know
      # about the underlying url fetching implementation.  TODO: consider a
      # bespoke fetcher implementation, also consider exponential backoff here.
      except HTTPError as e:
        print('Got HTTPError: %s..retrying' % e)
        time.sleep(0.1)
        self._reinit()
    return None
