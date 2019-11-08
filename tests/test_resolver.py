# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.common import safe_copy, temporary_dir
from pex.resolver import resolve_multi
from pex.testing import built_wheel, make_source_dir
from pex.third_party.pkg_resources import Requirement


def build_wheel(*args, **kwargs):
  with built_wheel(*args, **kwargs) as whl:
    return whl


def do_resolve_multi(*args, **kwargs):
  if 'indexes' not in kwargs:
    kwargs['indexes'] = []
  return list(resolve_multi(*args, **kwargs))


def test_empty_resolve():
  empty_resolve_multi = do_resolve_multi([])
  assert empty_resolve_multi == []

  with temporary_dir() as td:
    empty_resolve_multi = do_resolve_multi([], cache=td)
    assert empty_resolve_multi == []


def test_simple_local_resolve():
  project_wheel = build_wheel(name='project')

  with temporary_dir() as td:
    safe_copy(project_wheel, os.path.join(td, os.path.basename(project_wheel)))
    resolved_dists = do_resolve_multi(['project'], find_links=[td])
    assert len(resolved_dists) == 1


def test_diamond_local_resolve_cached():
  # This exercises the issue described here: https://github.com/pantsbuild/pex/issues/120
  project1_wheel = build_wheel(name='project1', install_reqs=['project2<1.0.0'])
  project2_wheel = build_wheel(name='project2')

  with temporary_dir() as dd:
    for wheel in (project1_wheel, project2_wheel):
      safe_copy(wheel, os.path.join(dd, os.path.basename(wheel)))
    with temporary_dir() as cd:
      resolved_dists = do_resolve_multi(['project1', 'project2'],
                                        find_links=[dd],
                                        cache=cd)
      assert len(resolved_dists) == 2


def test_cached_dependency_pinned_unpinned_resolution_multi_run():
  # This exercises the issue described here: https://github.com/pantsbuild/pex/issues/178
  project1_0_0 = build_wheel(name='project', version='1.0.0')
  project1_1_0 = build_wheel(name='project', version='1.1.0')

  with temporary_dir() as td:
    for wheel in (project1_0_0, project1_1_0):
      safe_copy(wheel, os.path.join(td, os.path.basename(wheel)))
    with temporary_dir() as cd:
      # First run, pinning 1.0.0 in the cache
      resolved_dists = do_resolve_multi(['project==1.0.0'],
                                        find_links=[td],
                                        cache=cd)
      assert len(resolved_dists) == 1
      assert resolved_dists[0].distribution.version == '1.0.0'

      # Second, run, the unbounded 'project' req will find the 1.0.0 in the cache. But should also
      # return SourcePackages found in td
      resolved_dists = do_resolve_multi(['project'],
                                        find_links=[td],
                                        cache=cd)
      assert len(resolved_dists) == 1
      assert resolved_dists[0].distribution.version == '1.1.0'


def test_intransitive():
  foo1_0 = build_wheel(name='foo', version='1.0.0')
  # The nonexistent req ensures that we are actually not acting transitively (as that would fail).
  bar1_0 = build_wheel(name='bar', version='1.0.0', install_reqs=['nonexistent==1.0.0'])
  with temporary_dir() as td:
    for wheel in (foo1_0, bar1_0):
      safe_copy(wheel, os.path.join(td, os.path.basename(wheel)))
    with temporary_dir() as cd:
      resolved_dists = do_resolve_multi(['foo', 'bar'],
                                        find_links=[td],
                                        cache=cd,
                                        transitive=False)
      assert len(resolved_dists) == 2


def test_resolve_prereleases():
  stable_dep = build_wheel(name='dep', version='2.0.0')
  prerelease_dep = build_wheel(name='dep', version='3.0.0rc3')

  with temporary_dir() as td:
    for wheel in (stable_dep, prerelease_dep):
      safe_copy(wheel, os.path.join(td, os.path.basename(wheel)))

    def assert_resolve(expected_version, **resolve_kwargs):
      resolved_dists = do_resolve_multi(['dep>=1,<4'], find_links=[td], **resolve_kwargs)
      assert 1 == len(resolved_dists)
      resolved_dist = resolved_dists[0]
      assert expected_version == resolved_dist.distribution.version

    assert_resolve('2.0.0')
    assert_resolve('2.0.0', allow_prereleases=False)
    assert_resolve('3.0.0rc3', allow_prereleases=True)


def _parse_requirement(req):
  return Requirement.parse(str(req))


def test_resolve_extra_setup_py():
  with make_source_dir(name='project1',
                       version='1.0.0',
                       extras_require={'foo': ['project2']}) as project1_dir:
    project2_wheel = build_wheel(name='project2', version='2.0.0')
    with temporary_dir() as td:
      safe_copy(project2_wheel, os.path.join(td, os.path.basename(project2_wheel)))

      resolved_dists = do_resolve_multi(['{}[foo]'.format(project1_dir)], find_links=[td])
      assert ({_parse_requirement(req) for req in ('project1==1.0.0',
                                                   'project2==2.0.0')} ==
              {_parse_requirement(resolved_dist.requirement) for resolved_dist in resolved_dists})


def test_resolve_extra_wheel():
  project1_wheel = build_wheel(name='project1',
                               version='1.0.0',
                               extras_require={'foo': ['project2']})
  project2_wheel = build_wheel(name='project2', version='2.0.0')
  with temporary_dir() as td:
    for wheel in (project1_wheel, project2_wheel):
      safe_copy(wheel, os.path.join(td, os.path.basename(wheel)))

    resolved_dists = do_resolve_multi(['project1[foo]'], find_links=[td])
    assert ({_parse_requirement(req) for req in ('project1==1.0.0', 'project2==2.0.0')} ==
            {_parse_requirement(resolved_dist.requirement) for resolved_dist in resolved_dists})
