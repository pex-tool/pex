import contextlib
import hashlib
import os
import shutil
import uuid
from abc import abstractmethod

from .common import safe_mkdtemp, safe_open
from .compatibility import AbstractClass, PY3
from .tracer import TRACER

try:
  import requests
except ImportError:
  requests = None

try:
  from cachecontrol import CacheControl
  from cachecontrol.caches import FileCache
except ImportError:
  CacheControl = FileCache = None

if PY3:
  import urllib.request as urllib_request
else:
  import urllib2 as urllib_request

# This is available as hashlib.algorithms_guaranteed in >=3.2 and as
# hashlib.algorithms in >=2.7, but not available in 2.6, so we enumerate
# here.
HASHLIB_ALGORITHMS = frozenset(['md5', 'sha1', 'sha224', 'sha256', 'sha384', 'sha512'])


class Context(AbstractClass):
  """Encapsulate the networking necessary to do requirement resolution.

  At a minimum, the Context must implement ``open(link)`` by returning a
  file-like object.  Reference implementations of ``read(link)`` and
  ``fetch(link)`` are provided based upon ``open(link)`` but may be further
  specialized by individual implementations.
  """

  class Error(Exception):
    """Error base class for Contexts to wrap application-specific exceptions."""
    pass

  _REGISTRY = []

  @classmethod
  def register(cls, context_impl):
    """Register a concrete implementation of a :class:`Context` to be recognized."""
    cls._REGISTRY.insert(0, context_impl)

  @classmethod
  def get(cls):
    for context_class in cls._REGISTRY:
      try:
        return context_class()
      except cls.Error:
        continue
    raise cls.Error('Could not initialize a request context.')

  @abstractmethod
  def open(self, link):
    """Return an open file-like object to the link.

    :param link: The :class:`Link` to open.
    """

  def read(self, link):
    """Return the binary content associated with the link.

    :param link: The :class:`Link` to read.
    """
    with contextlib.closing(self.open(link)) as fp:
      return fp.read()

  def fetch(self, link, into=None):
    """Fetch the binary content associated with the link and write to a file.

    :param link: The :class:`Link` to fetch.
    :keyword into: If specified, write into the directory ``into``.  If ``None``, creates a new
      temporary directory that persists for the duration of the interpreter.
    """
    target = os.path.join(into or safe_mkdtemp(), link.filename)

    if os.path.exists(target):
      # Assume that if the local file already exists, it is safe to use.
      return target

    with TRACER.timed('Fetching %s' % link.url, V=2):
      target_tmp = '%s.%s' % (target, uuid.uuid4())
      with contextlib.closing(self.open(link)) as in_fp:
        with safe_open(target_tmp, 'wb') as out_fp:
          shutil.copyfileobj(in_fp, out_fp)

    os.rename(target_tmp, target)
    return target


class UrllibContext(Context):
  """Default Python standard library Context."""

  def open(self, link):
    return urllib_request.urlopen(link.url)


Context.register(UrllibContext)


class StreamFilelike(object):
  """A file-like object wrapper around requests streams that performs hash validation."""

  @classmethod
  def detect_algorithm(cls, link):
    """Detect the hashing algorithm from the fragment in the link, if any."""
    if any(link.fragment.startswith('%s=' % algorithm) for algorithm in HASHLIB_ALGORITHMS):
      algorithm, value = link.fragment.split('=', 2)
      try:
        return hashlib.new(algorithm), value
      except ValueError:  # unsupported algorithm
        return None, None
    return None, None

  def __init__(self, request, link, chunk_size=16*1024):
    self._iterator = request.iter_content(chunk_size)
    self._bytes = b''
    self._link = link
    self._hasher, self._hash_value = self.detect_algorithm(link)

  def read(self, length=None):
    while length is None or len(self._bytes) < length:
      try:
        next_chunk = next(self._iterator)
        if self._hasher:
          self._hasher.update(next_chunk)
        self._bytes += next_chunk
      except StopIteration:
        self._validate()
        break
    if length is None:
      length = len(self._bytes)
    chunk, self._bytes = self._bytes[:length], self._bytes[length:]
    return chunk

  def _validate(self):
    if self._hasher:
      if self._hash_value != self._hasher.hexdigest():
        raise Context.Error('%s failed checksum!' % (self._link.url))
      else:
        TRACER.log('Validated %s (%s)' % (self._link.filename, self._link.fragment), V=3)

  def close(self):
    pass


class RequestsContext(Context):
  """A requests-based Context."""

  def __init__(self, session=None, verify=True):
    self._verify = verify
    self._session = session or requests.session()

  def open(self, link):
    # requests does not support file:// -- so we must short-circuit manually
    if link.local:
      return open(link.path, 'rb')
    try:
      return StreamFilelike(requests.get(link.url, verify=self._verify, stream=True), link)
    except requests.exceptions.RequestException as e:
      raise self.Error(e)


if requests:
  Context.register(RequestsContext)


class CachedRequestsContext(RequestsContext):
  """A requests-based Context with CacheControl support."""

  DEFAULT_CACHE = '~/.pex/cache'

  def __init__(self, cache=None, **kw):
    self._cache = os.path.realpath(os.path.expanduser(cache or self.DEFAULT_CACHE))
    super(CachedRequestsContext, self).__init__(
        CacheControl(requests.session(), cache=FileCache(self._cache)), **kw)


if CacheControl:
  Context.register(CachedRequestsContext)
