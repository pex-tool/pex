# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import os

import pytest

from pex.common import safe_copy, safe_mkdtemp, temporary_dir
from pex.compatibility import nested
from pex.interpreter import PythonInterpreter
from pex.resolver import resolve_multi
from pex.testing import (
    IS_LINUX,
    IS_PYPY,
    PY27,
    PY35,
    PY36,
    PY_VER,
    built_wheel,
    ensure_python_interpreter,
    make_source_dir
)
from pex.third_party.pkg_resources import Requirement


def build_wheel(*args, **kwargs):
  with built_wheel(*args, **kwargs) as whl:
    return whl


def local_resolve_multi(*args, **kwargs):
  # Skip remote lookups.
  kwargs['indexes'] = []
  return list(resolve_multi(*args, **kwargs))


def test_empty_resolve():
  empty_resolve_multi = local_resolve_multi([])
  assert empty_resolve_multi == []

  with temporary_dir() as td:
    empty_resolve_multi = local_resolve_multi([], cache=td)
    assert empty_resolve_multi == []


def test_simple_local_resolve():
  project_wheel = build_wheel(name='project')

  with temporary_dir() as td:
    safe_copy(project_wheel, os.path.join(td, os.path.basename(project_wheel)))
    resolved_dists = local_resolve_multi(['project'], find_links=[td])
    assert len(resolved_dists) == 1


def test_resolve_cache():
  project_wheel = build_wheel(name='project')

  with nested(temporary_dir(), temporary_dir()) as (td, cache):
    safe_copy(project_wheel, os.path.join(td, os.path.basename(project_wheel)))

    # Without a cache, each resolve should be isolated, but otherwise identical.
    resolved_dists1 = local_resolve_multi(['project'], find_links=[td])
    resolved_dists2 = local_resolve_multi(['project'], find_links=[td])
    assert resolved_dists1 != resolved_dists2
    assert len(resolved_dists1) == 1
    assert len(resolved_dists2) == 1
    assert resolved_dists1[0].requirement == resolved_dists2[0].requirement
    assert resolved_dists1[0].distribution.location != resolved_dists2[0].distribution.location

    # With a cache, each resolve should be identical.
    resolved_dists3 = local_resolve_multi(['project'], find_links=[td], cache=cache)
    resolved_dists4 = local_resolve_multi(['project'], find_links=[td], cache=cache)
    assert resolved_dists1 != resolved_dists3
    assert resolved_dists2 != resolved_dists3
    assert resolved_dists3 == resolved_dists4


def test_diamond_local_resolve_cached():
  # This exercises the issue described here: https://github.com/pantsbuild/pex/issues/120
  project1_wheel = build_wheel(name='project1', install_reqs=['project2<1.0.0'])
  project2_wheel = build_wheel(name='project2')

  with temporary_dir() as dd:
    for wheel in (project1_wheel, project2_wheel):
      safe_copy(wheel, os.path.join(dd, os.path.basename(wheel)))
    with temporary_dir() as cd:
      resolved_dists = local_resolve_multi(['project1', 'project2'],
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
      resolved_dists = local_resolve_multi(['project==1.0.0'],
                                           find_links=[td],
                                           cache=cd)
      assert len(resolved_dists) == 1
      assert resolved_dists[0].distribution.version == '1.0.0'

      # Second, run, the unbounded 'project' req will find the 1.0.0 in the cache. But should also
      # return SourcePackages found in td
      resolved_dists = local_resolve_multi(['project'],
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
      resolved_dists = local_resolve_multi(['foo', 'bar'],
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
      resolved_dists = local_resolve_multi(['dep>=1,<4'], find_links=[td], **resolve_kwargs)
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

      resolved_dists = local_resolve_multi(['{}[foo]'.format(project1_dir)], find_links=[td])
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

    resolved_dists = local_resolve_multi(['project1[foo]'], find_links=[td])
    assert ({_parse_requirement(req) for req in ('project1==1.0.0', 'project2==2.0.0')} ==
            {_parse_requirement(resolved_dist.requirement) for resolved_dist in resolved_dists})


def resolve_wheel_names(**kwargs):
  return [
    os.path.basename(resolved_distribution.distribution.location)
    for resolved_distribution in resolve_multi(**kwargs)
  ]


def resolve_p537_wheel_names(**kwargs):
  return resolve_wheel_names(requirements=['p537==1.0.4'], transitive=False, **kwargs)


@pytest.fixture(scope="module")
def p537_resolve_cache():
  return safe_mkdtemp()


@pytest.mark.skipif(PY_VER < (3, 5) or IS_PYPY,
                    reason="The p537 distribution only builds for CPython 3.5+")
def test_resolve_current_platform(p537_resolve_cache):
  resolve_current = functools.partial(resolve_p537_wheel_names,
                                      cache=p537_resolve_cache,
                                      platforms=['current'])

  other_python_version = PY36 if PY_VER == (3, 5) else PY35
  other_python = PythonInterpreter.from_binary(ensure_python_interpreter(other_python_version))
  current_python = PythonInterpreter.get()

  resolved_other = resolve_current(interpreters=[other_python])
  resolved_current = resolve_current()

  assert 1 == len(resolved_other)
  assert 1 == len(resolved_current)
  assert resolved_other != resolved_current
  assert resolved_current == resolve_current(interpreters=[current_python])
  assert resolved_current == resolve_current(interpreters=[current_python, current_python])

  # Here we have 2 local interpreters satisfying current but with different platforms and thus
  # different dists for 2 total dists.
  assert 2 == len(resolve_current(interpreters=[current_python, other_python]))


@pytest.mark.skipif(PY_VER < (3, 5) or IS_PYPY,
                    reason="The p537 distribution only builds for CPython 3.5+")
def test_resolve_current_and_foreign_platforms(p537_resolve_cache):
  foreign_platform = 'macosx-10.13-x86_64-cp-37-m' if IS_LINUX else 'manylinux1_x86_64-cp-37-m'
  resolve_current_and_foreign = functools.partial(resolve_p537_wheel_names,
                                                  cache=p537_resolve_cache,
                                                  platforms=['current', foreign_platform])

  assert 2 == len(resolve_current_and_foreign())

  other_python_version = PY36 if PY_VER == (3, 5) else PY35
  other_python = PythonInterpreter.from_binary(ensure_python_interpreter(other_python_version))
  current_python = PythonInterpreter.get()

  assert 2 == len(resolve_current_and_foreign(interpreters=[current_python]))
  assert 2 == len(resolve_current_and_foreign(interpreters=[other_python]))
  assert 2 == len(resolve_current_and_foreign(interpreters=[current_python, current_python]))

  # Here we have 2 local interpreters, satisfying current, but with different platforms and thus
  # different dists and then the foreign platform for 3 total dists.
  assert 3 == len(resolve_current_and_foreign(interpreters=[current_python, other_python]))


def test_resolve_foreign_abi3():
  # For version 2.8, cryptography publishes the following abi3 wheels for linux and macosx:
  # cryptography-2.8-cp34-abi3-macosx_10_6_intel.whl
  # cryptography-2.8-cp34-abi3-manylinux1_x86_64.whl
  # cryptography-2.8-cp34-abi3-manylinux2010_x86_64.whl

  cryptogrpahy_resolve_cache = safe_mkdtemp()
  foreign_ver = '37' if PY_VER == (3, 6) else '36'
  resolve_cryptography_wheel_names = functools.partial(
    resolve_wheel_names,
    requirements=['cryptography==2.8'],
    platforms=[
      'linux_x86_64-cp-{}-m'.format(foreign_ver),
      'macosx_10.11_x86_64-cp-{}-m'.format(foreign_ver)
    ],
    transitive=False,
    build=False,
    cache=cryptogrpahy_resolve_cache
  )

  wheel_names = resolve_cryptography_wheel_names(manylinux='manylinux2014')
  assert {
    'cryptography-2.8-cp34-abi3-manylinux2010_x86_64.whl',
    'cryptography-2.8-cp34-abi3-macosx_10_6_intel.whl'
  } == set(wheel_names)

  wheel_names = resolve_cryptography_wheel_names(manylinux='manylinux2010')
  assert {
    'cryptography-2.8-cp34-abi3-manylinux2010_x86_64.whl',
    'cryptography-2.8-cp34-abi3-macosx_10_6_intel.whl'
  } == set(wheel_names)

  wheel_names = resolve_cryptography_wheel_names(manylinux='manylinux1')
  assert {
    'cryptography-2.8-cp34-abi3-manylinux1_x86_64.whl',
    'cryptography-2.8-cp34-abi3-macosx_10_6_intel.whl'
  } == set(wheel_names)


def test_issues_851():
  # Previously, the PY36 resolve would fail post-resolution checks for configparser, pathlib2 and
  # contextlib2 which are only required for python_version<3.

  def resolve_pytest(python_version, pytest_version):
    interpreter = PythonInterpreter.from_binary(ensure_python_interpreter(python_version))
    resolved_dists = resolve_multi(interpreters=[interpreter],
                                           requirements=['pytest=={}'.format(pytest_version)])
    project_to_version = {rd.requirement.key: rd.distribution.version for rd in resolved_dists}
    assert project_to_version['pytest'] == pytest_version
    return project_to_version

  resolved_project_to_version = resolve_pytest(python_version=PY36, pytest_version='5.3.4')
  assert 'importlib-metadata' in resolved_project_to_version
  assert 'configparser' not in resolved_project_to_version
  assert 'pathlib2' not in resolved_project_to_version
  assert 'contextlib2' not in resolved_project_to_version

  resolved_project_to_version = resolve_pytest(python_version=PY27, pytest_version='4.6.9')
  assert 'importlib-metadata' in resolved_project_to_version
  assert 'configparser' in resolved_project_to_version
  assert 'pathlib2' in resolved_project_to_version
  assert 'contextlib2' in resolved_project_to_version
