# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.fetcher import PyPIFetcher


def test_pypifetcher():
  fetcher = PyPIFetcher('https://pypi.python.org/simple')
  assert fetcher._pypi_base == 'https://pypi.python.org/simple/'
  assert fetcher.urls('setuptools') == ['https://pypi.python.org/simple/setuptools/']

  fetcher = PyPIFetcher()
  assert fetcher._pypi_base == 'https://pypi.python.org/simple/'
  assert fetcher.urls('setuptools') == ['https://pypi.python.org/simple/setuptools/']

  fetcher = PyPIFetcher('file:///srv/simple')
  assert fetcher._pypi_base == 'file:///srv/simple/'
  assert fetcher.urls('setuptools') == ['file:///srv/simple/setuptools/']
