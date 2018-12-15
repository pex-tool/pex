# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import time

import pytest

from pex.common import safe_copy
from pex.crawler import Crawler
from pex.fetcher import Fetcher
from pex.package import EggPackage, SourcePackage
from pex.resolvable import ResolvableRequirement
from pex.resolver import Resolver, Unsatisfiable, _ResolvableSet, resolve_multi
from pex.resolver_options import ResolverOptionsBuilder
from pex.testing import make_sdist, temporary_dir


def do_resolve_multi(*args, **kwargs):
  return list(resolve_multi(*args, **kwargs))


def test_empty_resolve():
  empty_resolve_multi = do_resolve_multi([])
  assert empty_resolve_multi == []

  with temporary_dir() as td:
    empty_resolve_multi = do_resolve_multi([], cache=td)
    assert empty_resolve_multi == []


def test_simple_local_resolve():
  project_sdist = make_sdist(name='project')

  with temporary_dir() as td:
    safe_copy(project_sdist, os.path.join(td, os.path.basename(project_sdist)))
    fetchers = [Fetcher([td])]
    resolved_dists = do_resolve_multi(['project'], fetchers=fetchers)
    assert len(resolved_dists) == 1


def test_diamond_local_resolve_cached():
  # This exercises the issue described here: https://github.com/pantsbuild/pex/issues/120
  project1_sdist = make_sdist(name='project1', install_reqs=['project2<1.0.0'])
  project2_sdist = make_sdist(name='project2')

  with temporary_dir() as dd:
    for sdist in (project1_sdist, project2_sdist):
      safe_copy(sdist, os.path.join(dd, os.path.basename(sdist)))
    fetchers = [Fetcher([dd])]
    with temporary_dir() as cd:
      resolved_dists = do_resolve_multi(['project1', 'project2'],
                                        fetchers=fetchers,
                                        cache=cd,
                                        cache_ttl=1000)
      assert len(resolved_dists) == 2


def test_cached_dependency_pinned_unpinned_resolution_multi_run():
  # This exercises the issue described here: https://github.com/pantsbuild/pex/issues/178
  project1_0_0 = make_sdist(name='project', version='1.0.0')
  project1_1_0 = make_sdist(name='project', version='1.1.0')

  with temporary_dir() as td:
    for sdist in (project1_0_0, project1_1_0):
      safe_copy(sdist, os.path.join(td, os.path.basename(sdist)))
    fetchers = [Fetcher([td])]
    with temporary_dir() as cd:
      # First run, pinning 1.0.0 in the cache
      resolved_dists = do_resolve_multi(['project', 'project==1.0.0'],
                                        fetchers=fetchers,
                                        cache=cd,
                                        cache_ttl=1000)
      assert len(resolved_dists) == 1
      assert resolved_dists[0].distribution.version == '1.0.0'
      # This simulates separate invocations of pex but allows us to keep the same tmp cache dir
      Crawler.reset_cache()
      # Second, run, the unbounded 'project' req will find the 1.0.0 in the cache. But should also
      # return SourcePackages found in td
      resolved_dists = do_resolve_multi(['project', 'project==1.1.0'],
                                        fetchers=fetchers,
                                        cache=cd,
                                        cache_ttl=1000)
      assert len(resolved_dists) == 1
      assert resolved_dists[0].distribution.version == '1.1.0'
      # Third run, if exact resolvable and inexact resolvable, and cache_ttl is expired, exact
      # resolvable should pull from pypi as well since inexact will and the resulting
      # resolvable_set.merge() would fail.
      Crawler.reset_cache()
      time.sleep(1)
      resolved_dists = do_resolve_multi(['project', 'project==1.1.0'],
                                        fetchers=fetchers,
                                        cache=cd,
                                        cache_ttl=1)
      assert len(resolved_dists) == 1
      assert resolved_dists[0].distribution.version == '1.1.0'


def test_ambiguous_transitive_resolvable():
  # If an unbounded or larger bounded resolvable is resolved first, and a
  # transitive resolvable is resolved later in another round, Error(Ambiguous resolvable) can be
  # raised because foo pulls in foo-2.0.0 and bar->foo==1.0.0 pulls in foo-1.0.0.
  foo1_0 = make_sdist(name='foo', version='1.0.0')
  foo2_0 = make_sdist(name='foo', version='2.0.0')
  bar1_0 = make_sdist(name='bar', version='1.0.0', install_reqs=['foo==1.0.0'])
  with temporary_dir() as td:
    for sdist in (foo1_0, foo2_0, bar1_0):
      safe_copy(sdist, os.path.join(td, os.path.basename(sdist)))
    fetchers = [Fetcher([td])]
    with temporary_dir() as cd:
      resolved_dists = do_resolve_multi(['foo', 'bar'],
                                        fetchers=fetchers,
                                        cache=cd,
                                        cache_ttl=1000)
      assert len(resolved_dists) == 2
      assert resolved_dists[0].distribution.version == '1.0.0'


def test_resolve_prereleases():
  stable_dep = make_sdist(name='dep', version='2.0.0')
  prerelease_dep = make_sdist(name='dep', version='3.0.0rc3')

  with temporary_dir() as td:
    for sdist in (stable_dep, prerelease_dep):
      safe_copy(sdist, os.path.join(td, os.path.basename(sdist)))
    fetchers = [Fetcher([td])]

    def assert_resolve(expected_version, **resolve_kwargs):
      resolved_dists = do_resolve_multi(['dep>=1,<4'], fetchers=fetchers, **resolve_kwargs)
      assert 1 == len(resolved_dists)
      resolved_dist = resolved_dists[0]
      assert expected_version == resolved_dist.distribution.version

    assert_resolve('2.0.0')
    assert_resolve('2.0.0', allow_prereleases=False)
    assert_resolve('3.0.0rc3', allow_prereleases=True)


def test_resolve_prereleases_cached():
  stable_dep = make_sdist(name='dep', version='2.0.0')
  prerelease_dep = make_sdist(name='dep', version='3.0.0rc3')

  with temporary_dir() as td:
    for sdist in (stable_dep, prerelease_dep):
      safe_copy(sdist, os.path.join(td, os.path.basename(sdist)))
    fetchers = [Fetcher([td])]

    with temporary_dir() as cd:
      def assert_resolve(dep, expected_version, **resolve_kwargs):
        resolved_dists = do_resolve_multi([dep], cache=cd, cache_ttl=1000, **resolve_kwargs)
        assert 1 == len(resolved_dists)
        resolved_dist = resolved_dists[0]
        assert expected_version == resolved_dist.distribution.version

      Crawler.reset_cache()

      # First do a run to load it into the cache.
      assert_resolve('dep>=1,<4', '3.0.0rc3', allow_prereleases=True, fetchers=fetchers)

      # This simulates running from another pex command. The Crawler cache actually caches an empty
      # cache so this fails in the same "process".
      Crawler.reset_cache()

      # Now assert that we can get it from the cache by removing the source.
      assert_resolve('dep>=1,<4', '3.0.0rc3', allow_prereleases=True, fetchers=[])

      # It should also be able to resolve without allow_prereleases, if explicitly requested.
      Crawler.reset_cache()
      assert_resolve('dep>=1.rc1,<4', '3.0.0rc3', fetchers=[])


def test_resolve_prereleases_and_no_version():
  prerelease_dep = make_sdist(name='dep', version='3.0.0rc3')

  with temporary_dir() as td:
    safe_copy(prerelease_dep, os.path.join(td, os.path.basename(prerelease_dep)))
    fetchers = [Fetcher([td])]

    def assert_resolve(deps, expected_version, **resolve_kwargs):
      resolved_dists = do_resolve_multi(deps, fetchers=fetchers, **resolve_kwargs)
      assert 1 == len(resolved_dists)
      resolved_dist = resolved_dists[0]
      assert expected_version == resolved_dist.distribution.version

    # When allow_prereleases is specified, the requirement (from two dependencies)
    # for a specific pre-release version and no version specified, accepts the pre-release
    # version correctly.
    assert_resolve(['dep==3.0.0rc3', 'dep'], '3.0.0rc3', allow_prereleases=True)

    # Without allow_prereleases set, the pre-release version is rejected.
    # This used to be an issue when a command-line use did not pass the `--pre` option
    # correctly into the API call for resolve_multi() from build_pex() in pex.py.
    with pytest.raises(Unsatisfiable):
      assert_resolve(['dep==3.0.0rc3', 'dep'], '3.0.0rc3')


def test_resolve_prereleases_multiple_set():
  stable_dep = make_sdist(name='dep', version='2.0.0')
  prerelease_dep1 = make_sdist(name='dep', version='3.0.0rc3')
  prerelease_dep2 = make_sdist(name='dep', version='3.0.0rc4')
  prerelease_dep3 = make_sdist(name='dep', version='3.0.0rc5')

  with temporary_dir() as td:
    for sdist in (stable_dep, prerelease_dep1, prerelease_dep2, prerelease_dep3):
      safe_copy(sdist, os.path.join(td, os.path.basename(sdist)))
    fetchers = [Fetcher([td])]

    def assert_resolve(expected_version, **resolve_kwargs):
      resolved_dists = do_resolve_multi(['dep>=3.0.0rc1', 'dep==3.0.0rc4'],
                                        fetchers=fetchers,
                                        **resolve_kwargs)
      assert 1 == len(resolved_dists)
      resolved_dist = resolved_dists[0]
      assert expected_version == resolved_dist.distribution.version

    # This should resolve with explicit prerelease being set or implicitly.
    assert_resolve('3.0.0rc4', allow_prereleases=True)
    assert_resolve('3.0.0rc4')


def test_resolvable_set():
  builder = ResolverOptionsBuilder()
  rs = _ResolvableSet()
  rq = ResolvableRequirement.from_string('foo[ext]', builder)
  source_pkg = SourcePackage.from_href('foo-2.3.4.tar.gz')
  binary_pkg = EggPackage.from_href('Foo-2.3.4-py3.4.egg')

  rs.merge(rq, [source_pkg, binary_pkg])
  assert rs.get(source_pkg.name) == set([source_pkg, binary_pkg])
  assert rs.get(binary_pkg.name) == set([source_pkg, binary_pkg])
  assert rs.packages() == [(rq, set([source_pkg, binary_pkg]), None, False)]

  # test methods
  assert rs.extras('foo') == set(['ext'])
  assert rs.extras('Foo') == set(['ext'])

  # test filtering
  rs.merge(rq, [source_pkg])
  assert rs.get('foo') == set([source_pkg])
  assert rs.get('Foo') == set([source_pkg])

  with pytest.raises(Unsatisfiable):
    rs.merge(rq, [binary_pkg])


def test_resolvable_set_is_constraint_only():
  builder = ResolverOptionsBuilder()
  rs = _ResolvableSet()
  c = ResolvableRequirement.from_string('foo', builder)
  c.is_constraint = True

  package = SourcePackage.from_href('foo-2.3.4.tar.gz')
  rs.merge(c, [package])

  assert rs.packages() == [(c, set([package]), None, True)]


def test_resolvable_set_constraint_and_non_constraint():
  builder = ResolverOptionsBuilder()
  rs = _ResolvableSet()
  constraint = ResolvableRequirement.from_string('foo', builder)
  constraint.is_constraint = True

  package = SourcePackage.from_href('foo-2.3.4.tar.gz')

  rq = ResolvableRequirement.from_string('foo', builder)
  rs.merge(constraint, [package])
  rs.merge(rq, [package])

  assert rs.packages() == [(rq, set([package]), None, False)]


def test_constraints_limits_versions_usable():
  builder = ResolverOptionsBuilder()
  rs = _ResolvableSet()
  req = ResolvableRequirement.from_string("foo>0.5", builder)
  constraint = ResolvableRequirement.from_string("foo==0.7", builder)
  constraint.is_constraint = True

  version_packages = []
  for version in range(6, 10):
    version_string = "foo-0.{0}.tar.gz".format(version)
    package = SourcePackage.from_href(version_string)
    version_packages.append(package)
  rs.merge(req, version_packages)
  rs.merge(constraint, [version_packages[1]])
  assert rs.packages() == [(req, set([version_packages[1]]), None, False)]


def test_constraints_range():
  builder = ResolverOptionsBuilder()
  rs = _ResolvableSet()
  req = ResolvableRequirement.from_string("foo>0.5", builder)
  constraint = ResolvableRequirement.from_string("foo<0.9", builder)
  constraint.is_constraint = True

  version_packages = []
  for version in range(1, 10):
    version_string = "foo-0.{0}.tar.gz".format(version)
    package = SourcePackage.from_href(version_string)
    version_packages.append(package)
  rs.merge(req, version_packages[4:])
  rs.merge(constraint, version_packages[:8])
  assert rs.packages() == [(req, set(version_packages[4:8]), None, False)]


def test_resolver_with_constraint():
  builder = ResolverOptionsBuilder()
  r = Resolver()
  rs = _ResolvableSet()
  constraint = ResolvableRequirement.from_string('foo', builder)
  constraint.is_constraint = True

  package = SourcePackage.from_href('foo-2.3.4.tar.gz')

  rq = ResolvableRequirement.from_string('foo', builder)
  rs.merge(constraint, [package])
  rs.merge(rq, [package])
  assert r.resolve([], resolvable_set=rs) == []


def test_resolvable_set_built():
  builder = ResolverOptionsBuilder()
  rs = _ResolvableSet()
  rq = ResolvableRequirement.from_string('foo', builder)
  source_pkg = SourcePackage.from_href('foo-2.3.4.tar.gz')
  binary_pkg = EggPackage.from_href('foo-2.3.4-py3.4.egg')

  rs.merge(rq, [source_pkg])
  assert rs.get('foo') == set([source_pkg])
  assert rs.packages() == [(rq, set([source_pkg]), None, False)]

  with pytest.raises(Unsatisfiable):
    rs.merge(rq, [binary_pkg])

  updated_rs = rs.replace_built({source_pkg: binary_pkg})
  updated_rs.merge(rq, [binary_pkg])
  assert updated_rs.get('foo') == set([binary_pkg])
  assert updated_rs.packages() == [(rq, set([binary_pkg]), None, False)]
