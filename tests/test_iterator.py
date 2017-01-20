# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pkg_resources import Requirement

from pex.crawler import Crawler
from pex.fetcher import PyPIFetcher
from pex.iterator import Iterator
from pex.package import SourcePackage

try:
  from unittest import mock
except ImportError:
  import mock


def test_empty_iteration():
  crawler_mock = mock.create_autospec(Crawler, spec_set=True)
  crawler_mock.crawl.return_value = []
  iterator = Iterator(crawler=crawler_mock)

  assert list(iterator.iter(Requirement.parse('foo'))) == []
  assert len(crawler_mock.crawl.mock_calls) == 1
  _, args, kwargs = crawler_mock.crawl.mock_calls[0]
  assert list(args[0]) == list(PyPIFetcher().urls(Requirement.parse('foo')))
  assert kwargs == {'follow_links': False}


def assert_iteration(all_versions, *expected_versions, **iterator_kwargs):
  def package_url(version):
    return 'https://pypi.python.org/packages/source/p/pex/pex-%s.tar.gz' % version

  urls = [package_url(v) for v in all_versions]
  crawler_mock = mock.create_autospec(Crawler, spec_set=True)
  crawler_mock.crawl.return_value = urls
  iterator = Iterator(crawler=crawler_mock, follow_links=True, **iterator_kwargs)

  assert list(iterator.iter(Requirement.parse('pex'))) == [SourcePackage(package_url(v))
                                                           for v in expected_versions]
  assert len(crawler_mock.crawl.mock_calls) == 1
  _, _, kwargs = crawler_mock.crawl.mock_calls[0]
  assert kwargs == {'follow_links': True}


def test_iteration_with_return():
  assert_iteration(['0.8.6', '0.8.6b1'], '0.8.6')  # Iterator should exclude prereleases by default.
  assert_iteration(['0.8.6', '0.8.6b1'], '0.8.6', allow_prereleases=False)
  assert_iteration(['0.8.6', '0.8.6b1'], '0.8.6', '0.8.6b1', allow_prereleases=True)
