# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

import pytest

from pex.requirements import requirements_from_file, requirements_from_lines
from pex.resolvable import ResolvableRequirement
from pex.resolver_options import ResolverOptionsBuilder
from pex.testing import temporary_dir
from pex.third_party.pkg_resources import Requirement


def test_from_empty_lines():
  reqs = requirements_from_lines([])
  assert len(reqs) == 0

  reqs = requirements_from_lines(dedent("""
  # comment
  """).splitlines())
  assert len(reqs) == 0


@pytest.mark.parametrize('flag_separator', (' ', '='))
def test_line_types(flag_separator):
  reqs = requirements_from_lines(dedent("""
  simple_requirement
  specific_requirement==2
  --allow-external%sspecific_requirement
  """ % flag_separator).splitlines())

  # simple_requirement
  assert len(reqs) == 2
  assert isinstance(reqs[0], ResolvableRequirement)
  assert reqs[0].requirement == Requirement.parse('simple_requirement')
  assert not reqs[0].options._allow_external

  # specific_requirement
  assert isinstance(reqs[1], ResolvableRequirement)
  assert reqs[1].requirement == Requirement.parse('specific_requirement==2')
  assert reqs[1].options._allow_external


def test_all_external():
  reqs = requirements_from_lines(dedent("""
  simple_requirement
  specific_requirement==2
  --allow-all-external
  """).splitlines())
  assert reqs[0].options._allow_external
  assert reqs[1].options._allow_external


def test_allow_prereleases():
  # Prereleases should be disallowed by default.
  reqs = requirements_from_lines(dedent("""
  simple_requirement
  specific_requirement==2
  """).splitlines())
  assert not reqs[0].options._allow_prereleases
  assert not reqs[1].options._allow_prereleases

  reqs = requirements_from_lines(dedent("""
  --pre
  simple_requirement
  specific_requirement==2
  """).splitlines())
  assert reqs[0].options._allow_prereleases
  assert reqs[1].options._allow_prereleases


def test_index_types():
  reqs = requirements_from_lines(dedent("""
  simple_requirement
  --no-index
  """).splitlines())
  assert reqs[0].options._fetchers == []

  for prefix in ('-f ', '--find-links ', '--find-links='):
    reqs = requirements_from_lines(dedent("""
    foo
    --no-index
    %shttps://example.com/repo
    """ % prefix).splitlines())
    assert len(reqs[0].options._fetchers) == 1
    assert reqs[0].options._fetchers[0].urls('foo') == ['https://example.com/repo']

  for prefix in ('-i ', '--index-url ', '--index-url=', '--extra-index-url ', '--extra-index-url='):
    reqs = requirements_from_lines(dedent("""
    foo
    --no-index
    %shttps://example.com/repo/
    """ % prefix).splitlines())
    assert len(reqs[0].options._fetchers) == 1, 'Prefix is: %r' % prefix
    assert reqs[0].options._fetchers[0].urls('foo') == ['https://example.com/repo/foo/']


def test_nested_requirements():
  with temporary_dir() as td1:
    with temporary_dir() as td2:
      with open(os.path.join(td1, 'requirements.txt'), 'w') as fp:
        fp.write(dedent('''
            requirement1
            requirement2
            -r %s
            -r %s
        ''' % (
            os.path.join(td2, 'requirements_nonrelative.txt'),
            os.path.join('relative', 'requirements_relative.txt'))
        ))

      with open(os.path.join(td2, 'requirements_nonrelative.txt'), 'w') as fp:
        fp.write(dedent('''
        requirement3
        requirement4
        '''))

      os.mkdir(os.path.join(td1, 'relative'))
      with open(os.path.join(td1, 'relative', 'requirements_relative.txt'), 'w') as fp:
        fp.write(dedent('''
        requirement5
        requirement6
        '''))

      def rr(req):
        return ResolvableRequirement.from_string(req, ResolverOptionsBuilder())

      reqs = requirements_from_file(os.path.join(td1, 'requirements.txt'))
      assert reqs == [rr('requirement%d' % k) for k in (1, 2, 3, 4, 5, 6)]
