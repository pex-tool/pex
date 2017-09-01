# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
from contextlib import contextmanager
from io import BytesIO

import pytest

from pex.compatibility import PY2
from pex.http import Context, RequestsContext, StreamFilelike, UrllibContext
from pex.link import Link
from pex.util import named_temporary_file
from pex.variables import Variables

try:
  from unittest import mock
except ImportError:
  import mock

try:
  from responses import RequestsMock
except ImportError:
  RequestsMock = None

try:
  import requests
except ImportError:
  requests = None

BLOB = b'random blob of data'
NO_REQUESTS = 'RequestsMock is None or requests is None'


try:
  from httplib import HTTPMessage
except ImportError:
  from http.client import HTTPMessage


def make_md5(blob):
  md5 = hashlib.md5()
  md5.update(blob)
  return md5.hexdigest()


@contextmanager
def patch_requests():
  requests_mock = RequestsMock()
  requests_mock.start()
  yield requests_mock
  requests_mock.stop()


@contextmanager
def make_url(blob, md5_fragment=None):
  url = 'http://pypi.python.org/foo.tar.gz'
  if md5_fragment:
    url += '#md5=%s' % md5_fragment

  with patch_requests() as responses:
    responses.add(
        responses.GET,
        url,
        status=200,
        body=blob,
        content_type='application/x-compressed')

    yield url


@pytest.mark.skipif(NO_REQUESTS)
def test_stream_filelike_with_correct_md5():
  with make_url(BLOB, make_md5(BLOB)) as url:
    request = requests.get(url)
    filelike = StreamFilelike(request, Link.wrap(url))
    assert filelike.read() == BLOB


@pytest.mark.skipif(NO_REQUESTS)
def test_stream_filelike_with_incorrect_md5():
  with make_url(BLOB, 'f' * 32) as url:
    request = requests.get(url)
    filelike = StreamFilelike(request, Link.wrap(url))
    with pytest.raises(Context.Error):
      filelike.read()


@pytest.mark.skipif(NO_REQUESTS)
def test_stream_filelike_without_md5():
  with make_url(BLOB) as url:
    request = requests.get(url)
    filelike = StreamFilelike(request, Link.wrap(url))
    assert filelike.read() == BLOB


@pytest.mark.skipif(NO_REQUESTS)
def test_requests_context():
  context = RequestsContext(verify=False)

  with make_url(BLOB, make_md5(BLOB)) as url:
    assert context.read(Link.wrap(url)) == BLOB

  with make_url(BLOB, make_md5(BLOB)) as url:
    filename = context.fetch(Link.wrap(url))
    with open(filename, 'rb') as fp:
      assert fp.read() == BLOB

  # test local reading
  with named_temporary_file() as tf:
    tf.write(b'goop')
    tf.flush()
    assert context.read(Link.wrap(tf.name)) == b'goop'


class MockHttpLibResponse(BytesIO):
  def __init__(self, data):
    BytesIO.__init__(self, data)
    self.status = 200
    self.version = 'HTTP/1.1'
    self.reason = 'OK'
    if PY2:
      self.msg = HTTPMessage(BytesIO(b'Content-Type: application/x-compressed\r\n'))
    else:
      self.msg = HTTPMessage()
      self.msg.add_header('Content-Type', 'application/x-compressed')

  def getheaders(self):
    return list(self.msg.items())

  def isclosed(self):
    return self.closed


@pytest.mark.skipif(NO_REQUESTS)
def test_requests_context_invalid_retries():
  env = Variables(environ={'PEX_HTTP_RETRIES': '-1'})
  with pytest.raises(ValueError):
    RequestsContext(verify=False, env=env)


@pytest.mark.skipif(NO_REQUESTS)
def test_requests_context_retries_from_environment():
  retry_count = '42'
  env = Variables({'PEX_HTTP_RETRIES': retry_count})
  assert RequestsContext(verify=False, env=env)._max_retries == int(retry_count)


def timeout_side_effect(timeout_error=None, num_timeouts=1):
  timeout_error = timeout_error or requests.packages.urllib3.exceptions.ConnectTimeoutError
  url = 'http://pypi.python.org/foo.tar.gz'

  num_requests = [0]  # hack, because python closures?
  def timeout(*args, **kwargs):
    if num_requests[0] < num_timeouts:
      num_requests[0] += 1
      raise timeout_error(None, url, 'Time Out')
    else:
      return MockHttpLibResponse(BLOB)

  return url, timeout


@pytest.mark.skipif(NO_REQUESTS)
def test_requests_context_retries_connect_timeout():
  with mock.patch.object(
      requests.packages.urllib3.connectionpool.HTTPConnectionPool,
      '_make_request') as mock_make_request:

    url, mock_make_request.side_effect = timeout_side_effect()

    context = RequestsContext(verify=False)

    data = context.read(Link.wrap(url))
    assert data == BLOB


@pytest.mark.skipif(NO_REQUESTS)
def test_requests_context_retries_connect_timeout_retries_exhausted():
  with mock.patch.object(
      requests.packages.urllib3.connectionpool.HTTPConnectionPool,
      '_make_request') as mock_make_request:

    url, mock_make_request.side_effect = timeout_side_effect(num_timeouts=3)
    env = Variables(environ={'PEX_HTTP_RETRIES': '2'})

    context = RequestsContext(verify=False, env=env)

    with pytest.raises(Context.Error):
      context.read(Link.wrap(url))


@pytest.mark.skipif(NO_REQUESTS)
def test_requests_context_retries_read_timeout():
  with mock.patch.object(
      requests.packages.urllib3.connectionpool.HTTPConnectionPool,
      '_make_request') as mock_make_request:

    url, mock_make_request.side_effect = timeout_side_effect(
        timeout_error=requests.packages.urllib3.exceptions.ReadTimeoutError)

    context = RequestsContext(verify=False)

    data = context.read(Link.wrap(url))
    assert data == BLOB


@pytest.mark.skipif(NO_REQUESTS)
def test_requests_context_retries_read_timeout_retries_exhausted():
  with mock.patch.object(
      requests.packages.urllib3.connectionpool.HTTPConnectionPool,
      '_make_request') as mock_make_request:

    url, mock_make_request.side_effect = timeout_side_effect(
        timeout_error=requests.packages.urllib3.exceptions.ReadTimeoutError,
        num_timeouts=3)
    env = Variables(environ={'PEX_HTTP_RETRIES': '2'})

    context = RequestsContext(verify=False, env=env)

    with pytest.raises(Context.Error):
      context.read(Link.wrap(url))


def test_urllib_context_utf8_encoding():
  BYTES = b'this is a decoded utf8 string'

  with named_temporary_file() as tf:
    tf.write(BYTES)
    tf.flush()
    local_link = Link.wrap(tf.name)

    # Trick UrllibContext into thinking this is a remote link
    class MockUrllibContext(UrllibContext):
      def open(self, link):
        return super(MockUrllibContext, self).open(local_link)

    context = MockUrllibContext()
    assert context.content(Link.wrap('http://www.google.com')) == BYTES.decode(
        UrllibContext.DEFAULT_ENCODING)
