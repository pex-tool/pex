import contextlib
import errno
import os
import socket
import threading
import urllib2

from twitter.common.contextutil import temporary_dir
from twitter.common.lang import Compatibility
from twitter.common.python.http import CachedWeb, Web
from twitter.common.quantity import Amount, Time
from twitter.common.testing.clock import ThreadedClock

import mox
import pytest


# py2 vs py3 facepalm
if Compatibility.PY3:
  import urllib.error as urllib_error
  import urllib.parse as urlparse
  import urllib.request as urllib_request
else:
  import urllib2 as urllib_request
  import urllib2 as urllib_error
  import urlparse


# things that still need testing:
#    encoding of code + headers into .headers file
#


def test_open_resolve_failure():
  m = mox.Mox()
  m.StubOutWithMock(socket, 'gethostbyname')
  socket.gethostbyname('www.google.com').AndRaise(
      socket.gaierror(errno.EADDRNOTAVAIL, 'Could not resolve host.'))
  m.ReplayAll()
  with pytest.raises(urllib_error.URLError):
    Web().open('http://www.google.com')
  m.UnsetStubs()
  m.VerifyAll()


def test_resolve_timeout():
  event = threading.Event()
  class FakeWeb(Web):
    NS_TIMEOUT = Amount(1, Time.MILLISECONDS)
    def _resolves(self, fullurl):
      event.wait()
    def _reachable(self, fullurl):
      return True
  with pytest.raises(urllib_error.URLError):
    FakeWeb().open('http://www.google.com')
  # unblock anonymous thread
  event.set()


def test_unreachable_error():
  m = mox.Mox()
  m.StubOutWithMock(socket, 'gethostbyname')
  m.StubOutWithMock(socket, 'create_connection')
  socket.gethostbyname('www.google.com').AndReturn('1.2.3.4')
  socket.create_connection(('www.google.com', 80), timeout=mox.IgnoreArg()).AndRaise(
      socket.error(errno.ENETUNREACH, 'Could not reach network.'))
  m.ReplayAll()
  with pytest.raises(urllib_error.URLError):
    Web().open('http://www.google.com')
  m.UnsetStubs()
  m.VerifyAll()


def test_local_open():
  m = mox.Mox()
  m.StubOutWithMock(urllib_request, 'urlopen')
  urllib_request.urlopen('file:///local/filename').AndReturn('data')
  m.ReplayAll()
  assert Web().open('/local/filename') == 'data'
  m.UnsetStubs()
  m.VerifyAll()


def test_maybe_local():
  maybe_local = Web().maybe_local_url
  assert maybe_local('http://www.google.com') == 'http://www.google.com'
  assert maybe_local('https://www.google.com/whatever') == 'https://www.google.com/whatever'
  assert maybe_local('tmp/poop.txt') == 'file://tmp/poop.txt'
  assert maybe_local('/tmp/poop.txt') == 'file:///tmp/poop.txt'
  assert maybe_local('www.google.com') == 'file://www.google.com'


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
    if conn_timeout and conn_timeout == Amount(0, Time.SECONDS):
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
  with pytest.raises(urllib_error.URLError):
    with contextlib.closing(web.open(URL, conn_timeout=Amount(0, Time.SECONDS))):
      pass
  with contextlib.closing(web.open(URL, conn_timeout=Amount(10, Time.MILLISECONDS))) as fp:
    assert fp.read() == DATA


def test_caching():
  URL = 'http://www.google.com'
  DATA = b'This is google.com!'
  clock = ThreadedClock()
  m = mox.Mox()
  m.StubOutWithMock(os.path, 'getmtime')
  os.path.getmtime(mox.IgnoreArg()).MultipleTimes().AndReturn(0)
  m.ReplayAll()

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

  m.UnsetStubs()
  m.VerifyAll()
