# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest

from pex.link import Link


def test_link_wrapping():
  link = Link.wrap('https://www.google.com')
  assert link.url == 'https://www.google.com'

  link = Link.wrap(Link.wrap('https://www.google.com'))
  assert link.url == 'https://www.google.com'

  with pytest.raises(ValueError):
    Link.wrap(1234)

  with pytest.raises(ValueError):
    Link.wrap_iterable(1234)

  links = Link.wrap_iterable('https://www.google.com')
  assert len(links) == 1
  assert links[0].url == 'https://www.google.com'

  links = Link.wrap_iterable(['https://www.google.com', Link('http://www.google.com')])
  assert set(links) == set([
      Link('http://www.google.com'),
      Link('https://www.google.com'),
  ])


def test_link_join():
  link = Link('https://www.google.com/bar/')
  assert link.join('/foo').url == 'https://www.google.com/foo'
  assert link.join('#foo').url == 'https://www.google.com/bar/#foo'
  assert link.join('foo').url == 'https://www.google.com/bar/foo'


def test_link_schemes():
  link = Link('http://www.google.com')
  assert link.scheme == 'http'
  assert link.remote

  link = Link('https://www.google.com')
  assert link.scheme == 'https'
  assert link.remote

  link = Link('/foo/bar')
  assert link.scheme == 'file'
  assert link.local
  assert link.path == os.path.realpath('/foo/bar')
