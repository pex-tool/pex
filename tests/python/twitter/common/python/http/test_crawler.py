import contextlib
import os

from twitter.common.contextutil import temporary_dir
from twitter.common.python.http.crawler import Crawler, PageParser

from base import create_layout


def lpp(page):
  links = PageParser.links(page)
  rels = PageParser.rel_links(page)
  return list(links), list(rels)


def test_page_parser_empty():
  links, rels = lpp("")
  assert links == []
  assert rels == []


def test_page_parser_basic():
  for target in ('href', 'href =', 'href =""'): #, 'href= ""'):
    assert lpp(target.lower()) == ([], [])
    assert lpp(target.upper()) == ([], [])
  for target in ('a href=', 'a href=""'):
    assert lpp(target.lower()) == ([''], [])
    assert lpp(target.upper()) == ([''], [])
  assert lpp('a href=11') == (['11'], [])
  assert lpp('a href=12') == (['12'], [])
  for href in ('pooping', '{};a[32[32{#@'):
    for start, end in ( ('', ''), ('"', '"'), ("'", "'") ):
      target = '%s%s%s' % (start, href, end)
      assert lpp('<a href=%s>' % target) == ([href], [])
      assert lpp("<a href=%s>" % target) == ([href], [])
      assert lpp('anything <a href=%s> anything' % target) == ([href], [])
      assert lpp("<a href=%s> <a href='stuff'>" % target) == ([href, 'stuff'], [])
      assert lpp("<a href='stuff'> <a href=%s>" % target) == (['stuff', href], [])


def test_page_parser_rels():
  VALID_RELS = tuple(PageParser.REL_TYPES)
  for rel in VALID_RELS + ('', ' ', 'blah'):
    for start, end in ( ('', ''), ('"', '"'), ("'", "'") ):
      target = 'rel=%s%s%s' % (start, rel, end)
      links, rels = lpp("<a href='things' %s> <a href='stuff'>" % target)
      assert links == ['things', 'stuff']
      if rel in VALID_RELS:
        assert rels == ['things']
      else:
        assert rels == []
      links, rels = lpp("<a href='stuff' %s> <a href='things'>" % target)
      assert links == ['stuff', 'things']
      if rel in VALID_RELS:
        assert rels == ['stuff']
      else:
        assert rels == []

def test_page_parser_skips_data_rels():
  for ext in PageParser.REL_SKIP_EXTENSIONS:
    things = 'things%s' % ext
    assert lpp("<a href='%s' rel=download>" % things) == ([things], [])
  for ext in ('.html', '.xml', '', '.txt', '.tar.gz.txt'):
    things = 'things%s' % ext
    assert lpp("<a href='%s' rel=download>" % things) == ([things], [things])


def test_crawler_local():
  FL = ('a.txt', 'b.txt', 'c.txt')
  with temporary_dir() as td:
    for fn in FL:
      with open(os.path.join(td, fn), 'w') as fp:
        pass
    for dn in (1, 2):
      os.mkdir(os.path.join(td, 'dir%d' % dn))
      for fn in FL:
        with open(os.path.join(td, 'dir%d' % dn, fn), 'w') as fp:
          pass

    # basic file / dir rel splitting
    links, rels = Crawler(enable_cache=False).execute(td)
    assert set(links) == set(os.path.join(td, fn) for fn in FL)
    assert set(rels) == set(os.path.join(td, 'dir%d' % n) for n in (1, 2))

    # recursive crawling, single vs multi-threaded
    for caching in (False, True):
      for threads in (1, 2, 3):
        links = Crawler(enable_cache=caching, threads=threads).crawl(td)
        expect_links = (set(os.path.join(td, fn) for fn in FL) |
                        set(os.path.join(td, 'dir1', fn) for fn in FL) |
                        set(os.path.join(td, 'dir2', fn) for fn in FL))
        assert set(links) == expect_links


def test_crawler_unknown_scheme():
  # skips unknown url schemes
  Crawler(enable_cache=False).execute('ftp://ftp.cdrom.com') == (set(), set())


# TODO(wickman)
#   test remote http crawling via mock
#   test page decoding via mock
