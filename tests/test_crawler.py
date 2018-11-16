# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.crawler import Crawler, PageParser
from pex.http import Context
from pex.link import Link
from pex.testing import temporary_dir

try:
  from unittest import mock
except ImportError:
  import mock


def lpp(page):
  links = PageParser.links(page)
  rels = PageParser.rel_links(page)
  return list(links), list(rels)


def test_page_parser_empty():
  links, rels = lpp("")
  assert links == []
  assert rels == []


def test_page_parser_basic():
  for target in ('href', 'href =', 'href =""'):
    assert lpp(target.lower()) == ([], [])
    assert lpp(target.upper()) == ([], [])
  for target in ('a href=', 'a href=""'):
    assert lpp(target.lower()) == ([''], [])
    assert lpp(target.upper()) == ([''], [])
  assert lpp('a href=11') == (['11'], [])
  assert lpp('a href=12') == (['12'], [])
  for href in ('pooping', '{};a[32[32{#@'):
    for start, end in (('', ''), ('"', '"'), ("'", "'")):
      target = '%s%s%s' % (start, href, end)
      assert lpp('<a href=%s>' % target) == ([href], [])
      assert lpp("<a href=%s>" % target) == ([href], [])
      assert lpp('anything <a href=%s> anything' % target) == ([href], [])
      assert lpp("<a href=%s> <a href='stuff'>" % target) == ([href, 'stuff'], [])
      assert lpp("<a href='stuff'> <a href=%s>" % target) == (['stuff', href], [])


def test_page_parser_escaped_html():
  url = 'url?param1=val&param2=val2'
  link = 'a href="%s"' % url.replace('&', '&amp;')
  assert lpp(link) == ([url], [])


def test_page_parser_rels():
  VALID_RELS = tuple(PageParser.REL_TYPES)
  for rel in VALID_RELS + ('', ' ', 'blah'):
    for start, end in (('', ''), ('"', '"'), ("'", "'")):
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
      with open(os.path.join(td, fn), 'w'):
        pass
    for dn in (1, 2):
      os.mkdir(os.path.join(td, 'dir%d' % dn))
      for fn in FL:
        with open(os.path.join(td, 'dir%d' % dn, fn), 'w'):
          pass

    # basic file / dir rel splitting
    links, rels = Crawler.crawl_local(Link.wrap(td))
    assert set(links) == set(Link.wrap(os.path.join(td, fn)) for fn in FL)
    assert set(rels) == set(Link.wrap(os.path.join(td, 'dir%d' % n)) for n in (1, 2))

    # recursive crawling, single vs multi-threaded
    for caching in (False, True):
      for threads in (1, 2, 3):
        links = Crawler(threads=threads).crawl([td], follow_links=True)
        expect_links = (set(Link.wrap(os.path.join(td, fn)) for fn in FL) |
                        set(Link.wrap(os.path.join(td, 'dir1', fn)) for fn in FL) |
                        set(Link.wrap(os.path.join(td, 'dir2', fn)) for fn in FL))
        assert set(links) == expect_links


def test_crawler_unknown_scheme():
  # skips unknown url schemes
  Crawler().crawl('ftp://ftp.cdrom.com') == (set(), set())


MOCK_INDEX_TMPL = '''
<h1>Index of /home/third_party/python</h1>
<table>
<tr>
  <td valign="top"><img src="/icons/back.gif" alt="[DIR]"></td>
  <td>&nbsp;</td>
  <td align="right">  - </td>
  <td>&nbsp;</td>
</tr>
%s
</table>
'''

MOCK_INDEX_A = MOCK_INDEX_TMPL % '''
<tr>
  <td valign="top"><img src="/icons/compressed.gif" alt="[   ]"></td>
  <td><a href="3to2-1.0.tar.gz">3to2-1.0.tar.gz</a></td>
  <td align="right">16-Apr-2015 23:18  </td>
  <td align="right"> 45K</td>
  <td>GZIP compressed docume></td>
</tr>
'''

MOCK_INDEX_B = MOCK_INDEX_TMPL % '''
<tr>
  <td valign="top"><img src="/icons/compressed.gif" alt="[   ]"></td>
  <td>
    <a href="APScheduler-2.1.0.tar.gz">APScheduler-2.1.0.tar.gz</a>
  </td>
  <td align="right">16-Apr-2015 23:18  </td>
  <td align="right"> 41K</td>
  <td>GZIP compressed docume></td>
</tr>
'''


def test_crawler_remote():
  Crawler.reset_cache()

  mock_context = mock.create_autospec(Context, spec_set=True)
  mock_context.resolve = lambda link: link
  mock_context.content.side_effect = [MOCK_INDEX_A, MOCK_INDEX_B, Exception('shouldnt get here')]
  expected_output = set([Link('http://url1.test.com/3to2-1.0.tar.gz'),
                         Link('http://url2.test.com/APScheduler-2.1.0.tar.gz')])

  c = Crawler(mock_context)
  test_links = [Link('http://url1.test.com'), Link('http://url2.test.com')]
  assert c.crawl(test_links) == expected_output

  # Test memoization of Crawler.crawl().
  assert c.crawl(test_links) == expected_output


def test_crawler_remote_redirect():
  Crawler.reset_cache()

  mock_context = mock.create_autospec(Context, spec_set=True)
  mock_context.resolve = lambda link: Link('http://url2.test.com')
  mock_context.content.side_effect = [MOCK_INDEX_A]
  expected_output = set([Link('http://url2.test.com/3to2-1.0.tar.gz')])

  c = Crawler(mock_context)
  test_links = [Link('http://url1.test.com')]
  assert c.crawl(test_links) == expected_output


# TODO(wickman): test page decoding via mock
