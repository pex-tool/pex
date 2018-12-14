# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

import pex.third_party.pkg_resources as pkg_resources
from pex.interpreter import PythonInterpreter
from pex.iterator import Iterator
from pex.package import Package, SourcePackage
from pex.resolvable import (
    Resolvable,
    ResolvableDirectory,
    ResolvablePackage,
    ResolvableRepository,
    ResolvableRequirement,
    resolvables_from_iterable
)
from pex.resolver_options import ResolverOptionsBuilder
from pex.testing import make_source_dir

try:
  from unittest import mock
except ImportError:
  import mock


def test_resolvable_package():
  builder = ResolverOptionsBuilder()
  source_name = 'foo-2.3.4.tar.gz'
  pkg = SourcePackage.from_href(source_name)
  resolvable = ResolvablePackage.from_string(source_name, builder)
  assert resolvable.packages() == [pkg]

  mock_iterator = mock.create_autospec(Iterator, spec_set=True)
  mock_iterator.iter.return_value = iter([])
  # fetchers are currently unused for static packages.
  assert resolvable.compatible(mock_iterator) == []
  assert mock_iterator.iter.mock_calls == []
  assert resolvable.name == 'foo'
  assert resolvable.exact is True
  assert resolvable.extras() == []

  resolvable = ResolvablePackage.from_string(source_name + '[extra1,extra2]', builder)
  assert resolvable.extras() == ['extra1', 'extra2']

  assert Resolvable.get('foo-2.3.4.tar.gz') == ResolvablePackage.from_string(
      'foo-2.3.4.tar.gz', builder)

  with pytest.raises(ResolvablePackage.InvalidRequirement):
    ResolvablePackage.from_string('foo', builder)


def test_resolvable_repository():
  # not yet implemented
  with pytest.raises(Resolvable.InvalidRequirement):
    ResolvableRepository.from_string('git+http://github.com/wickman/pex',
        ResolverOptionsBuilder())


def test_resolvable_requirement():
  req = 'foo[bar]==2.3.4'
  resolvable = ResolvableRequirement.from_string(req, ResolverOptionsBuilder(fetchers=[]))
  assert resolvable.requirement == pkg_resources.Requirement.parse('foo[bar]==2.3.4')
  assert resolvable.name == 'foo'
  assert resolvable.exact is True
  assert resolvable.extras() == ['bar']
  assert resolvable.options._fetchers == []
  assert resolvable.packages() == []

  source_pkg = SourcePackage.from_href('foo-2.3.4.tar.gz')
  mock_iterator = mock.create_autospec(Iterator, spec_set=True)
  mock_iterator.iter.return_value = iter([source_pkg])
  assert resolvable.compatible(mock_iterator) == [source_pkg]
  assert mock_iterator.iter.mock_calls == [
      mock.call(pkg_resources.Requirement.parse('foo[bar]==2.3.4'))]

  # test non-exact
  resolvable = ResolvableRequirement.from_string('foo', ResolverOptionsBuilder())
  assert resolvable.exact is False

  # test Resolvable.get, which should delegate to a ResolvableRequirement in this case
  assert Resolvable.get('foo') == ResolvableRequirement.from_string(
      'foo', ResolverOptionsBuilder())


def test_resolvable_directory():
  builder = ResolverOptionsBuilder()
  interpreter = PythonInterpreter.get()

  with make_source_dir(name='my_project') as td:
    rdir = ResolvableDirectory.from_string(td, builder, interpreter)
    assert rdir.name == pkg_resources.safe_name('my_project')
    assert rdir.extras() == []

    rdir = ResolvableDirectory.from_string(td + '[extra1,extra2]', builder, interpreter)
    assert rdir.name == pkg_resources.safe_name('my_project')
    assert rdir.extras() == ['extra1', 'extra2']


def test_resolvables_from_iterable():
  builder = ResolverOptionsBuilder()

  reqs = [
      'foo',  # string
      Package.from_href('foo-2.3.4.tar.gz'),  # Package
      pkg_resources.Requirement.parse('foo==2.3.4'),
  ]

  resolved_reqs = list(resolvables_from_iterable(reqs, builder))

  assert resolved_reqs == [
      ResolvableRequirement.from_string('foo', builder),
      ResolvablePackage.from_string('foo-2.3.4.tar.gz', builder),
      ResolvableRequirement.from_string('foo==2.3.4', builder),
  ]


def test_resolvable_is_constraint_getter_setter():
  builder = ResolverOptionsBuilder()
  req = ResolvableRequirement.from_string('foo', builder)
  assert req.is_constraint is False
  req.is_constraint = True
  assert req.is_constraint is True
