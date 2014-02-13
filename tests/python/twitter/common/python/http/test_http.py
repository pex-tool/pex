import contextlib
import errno
import os
import socket
import threading

from twitter.common.contextutil import temporary_dir
from twitter.common.lang import Compatibility
from twitter.common.python.http import CachedWeb, Web, FetchError
from twitter.common.testing.clock import ThreadedClock

import pytest


if Compatibility.PY3:
  from unittest import mock
  import urllib.error as urllib_error
  import urllib.parse as urlparse
  import urllib.request as urllib_request
  URLLIB_REQUEST = 'urllib.request'
else:
  import mock
  import urllib2 as urllib_request
  import urllib2 as urllib_error
  import urlparse
  URLLIB_REQUEST = 'urllib2'


# TODO(wickman) things that still need testing: encoding of code + headers into .headers file


@mock.patch('socket.gethostbyname')
def test_open_resolve_failure(gethostbyname_mock):
  gethostbyname_mock.side_effect = socket.gaierror(errno.EADDRNOTAVAIL, 'Could not resolve host.')
  with pytest.raises(urllib_error.URLError):
    Web().open('http://www.google.com')


def test_resolve_timeout():
  event = threading.Event()
  class FakeWeb(Web):
    NS_TIMEOUT_SECS = 0.001
    def _resolves(self, fullurl):
      event.wait()
    def _reachable(self, fullurl):
      return True
  with pytest.raises(urllib_error.URLError):
    FakeWeb().open('http://www.google.com')
  # unblock anonymous thread
  event.set()


@mock.patch('socket.gethostbyname')
@mock.patch('socket.create_connection')
def test_unreachable_error(create_connection_mock, gethostbyname_mock):
  gethostbyname_mock.return_value = '1.2.3.4'
  create_connection_mock.side_effect = socket.error(errno.ENETUNREACH,
      'Could not reach network.')
  with pytest.raises(urllib_error.URLError):
    Web().open('http://www.google.com')
  gethostbyname_mock.assert_called_once_with('www.google.com')


@mock.patch('%s.urlopen' % URLLIB_REQUEST)
def test_local_open(urlopen_mock):
  urlopen_mock.return_value = 'data'
  assert Web().open('/local/filename') == 'data'


def test_maybe_local():
  maybe_local = Web().maybe_local_url
  assert maybe_local('http://www.google.com') == 'http://www.google.com'
  assert maybe_local('https://www.google.com/whatever') == 'https://www.google.com/whatever'
  assert maybe_local('tmp/poop.txt') == 'file://' + os.path.realpath('tmp/poop.txt')
  assert maybe_local('/tmp/poop.txt') == 'file://' + os.path.realpath('/tmp/poop.txt')
  assert maybe_local('www.google.com') == 'file://' + os.path.realpath('www.google.com')


class MockOpener(object):
  DEFAULT_DATA = b'Blah blah blahhhhh'

  def __init__(self, rv=DEFAULT_DATA, code=200):
    self.rv = rv
    self.code = code
    self.opened = threading.Event()
    self.error = None

  def clear(self):
    self.opened.clear()

  def open(self, url, conn_timeout=None):
    if conn_timeout == 0:
      raise urllib_error.URLError('Could not reach %s within deadline.' % url)
    if url.startswith('http'):
      self.opened.set()
    if self.error:
      raise urllib_error.HTTPError(url, self.error, None, None, Compatibility.BytesIO(b'glhglhg'))
    return urllib_request.addinfourl(Compatibility.BytesIO(self.rv), url, None, self.code)


def test_connect_timeout_using_open():
  URL = 'http://www.google.com'
  DATA = b'This is google.com!'

  clock = ThreadedClock()
  opener = MockOpener(DATA)
  web = CachedWeb(clock=clock, opener=opener)
  assert not os.path.exists(web.translate_url(URL))
  with pytest.raises(FetchError):
    with contextlib.closing(web.open(URL, conn_timeout=0)):
      pass
  with contextlib.closing(web.open(URL, conn_timeout=0.01)) as fp:
    assert fp.read() == DATA


@mock.patch('os.path.getmtime')
def test_caching(getmtime_mock):
  URL = 'http://www.google.com'
  DATA = b'This is google.com!'
  clock = ThreadedClock()
  getmtime_mock.return_value = 0

  opener = MockOpener(DATA)
  web = CachedWeb(clock=clock, opener=opener)
  assert not os.path.exists(web.translate_url(URL))
  with contextlib.closing(web.open(URL)) as fp:
    assert fp.read() == DATA
  assert os.path.exists(web.translate_url(URL))
  assert opener.opened.is_set()
  opener.clear()

  assert web.expired(URL, ttl=0.5) is False
  clock.tick(1)
  assert web.expired(URL, ttl=0.5)

  with contextlib.closing(web.open(URL)) as fp:
    assert fp.read() == DATA
  assert not opener.opened.is_set()

  with contextlib.closing(web.open(URL, ttl=0.5)) as fp:
    assert fp.read() == DATA
  assert opener.opened.is_set(), 'expect expired url to cause http get'
