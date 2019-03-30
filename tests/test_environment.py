# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import platform
import subprocess
from contextlib import contextmanager
from textwrap import dedent

import pytest

from pex import resolver
from pex.compatibility import PY2, nested, to_bytes
from pex.environment import PEXEnvironment
from pex.installer import EggInstaller, WheelInstaller
from pex.interpreter import PythonInterpreter
from pex.package import SourcePackage, WheelPackage
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.resolver import resolve
from pex.testing import (
    PY35,
    ensure_python_interpreter,
    make_bdist,
    temporary_content,
    temporary_dir,
    temporary_filename
)


@contextmanager
def yield_pex_builder(zip_safe=True, installer_impl=EggInstaller, interpreter=None):
  with nested(temporary_dir(),
              make_bdist('p1',
                         zipped=True,
                         zip_safe=zip_safe,
                         installer_impl=installer_impl,
                         interpreter=interpreter)) as (td, p1):
    pb = PEXBuilder(path=td, interpreter=interpreter)
    pb.add_dist_location(p1.location)
    yield pb


def test_force_local():
  with nested(yield_pex_builder(), temporary_dir(), temporary_filename()) as (
          pb, pex_root, pex_file):
    pb.info.pex_root = pex_root
    pb.build(pex_file)

    code_cache = PEXEnvironment.force_local(pex_file, pb.info)
    assert os.path.exists(pb.info.zip_unsafe_cache)
    assert len(os.listdir(pb.info.zip_unsafe_cache)) == 1
    assert [os.path.basename(code_cache)] == os.listdir(pb.info.zip_unsafe_cache)
    assert set(os.listdir(code_cache)) == set([PexInfo.PATH, '__main__.py', '__main__.pyc'])

    # idempotence
    assert PEXEnvironment.force_local(pex_file, pb.info) == code_cache


def assert_force_local_implicit_ns_packages_issues_598(interpreter=None,
                                                       requirements=(),
                                                       create_ns_packages=True):

  def create_foo_bar_setup(name, **extra_args):
    setup_args = dict(
      name=name,
      version='0.0.1',
      packages=['foo', 'foo.bar']
    )
    if create_ns_packages:
      setup_args.update(namespace_packages=['foo', 'foo.bar'])
    if requirements:
      setup_args.update(install_requires=list(requirements))
    setup_args.update(extra_args)

    return dedent("""
      from setuptools import setup

      setup(**{setup_args!r})
    """.format(setup_args=setup_args))

  def with_foo_bar_ns_packages(content):
    ns_packages = {
      os.path.join(pkg, '__init__.py'): '__import__("pkg_resources").declare_namespace(__name__)'
      for pkg in ('foo', 'foo/bar')
    } if create_ns_packages else {}
    ns_packages.update(content)
    return ns_packages

  content1 = with_foo_bar_ns_packages({
    'foo/bar/spam.py': 'identify = lambda: 42',
    'setup.py': create_foo_bar_setup('foo-bar-spam')
  })

  content2 = with_foo_bar_ns_packages({
    'foo/bar/eggs.py': dedent("""
      # NB: This only works when this content is unpacked loose on the filesystem!
      def read_self():
        with open(__file__) as fp:
          return fp.read()
    """)
  })

  content3 = with_foo_bar_ns_packages({
    'foobaz': dedent("""\
      #!python
      import sys

      from foo.bar import baz

      sys.exit(baz.main())
    """),
    'foo/bar/baz.py': dedent("""
      import sys

      from foo.bar import eggs, spam

      def main():
        assert len(eggs.read_self()) > 0
        return spam.identify()
    """),
    'setup.py': create_foo_bar_setup('foo-bar-baz', scripts=['foobaz'])
  })

  def add_requirements(builder, cache):
    for resolved_dist in resolve(requirements, cache=cache, interpreter=builder.interpreter):
      builder.add_requirement(resolved_dist.requirement)
      builder.add_distribution(resolved_dist.distribution)

  def add_wheel(builder, content):
    with temporary_content(content) as project:
      dist = WheelInstaller(project, interpreter=builder.interpreter).bdist()
      builder.add_dist_location(dist)

  def add_sources(builder, content):
    with temporary_content(content) as project:
      for path in content.keys():
        builder.add_source(os.path.join(project, path), path)

  with nested(temporary_dir(), temporary_dir()) as (root, cache):
    pex_info1 = PexInfo.default()
    pex_info1.zip_safe = False
    pex1 = os.path.join(root, 'pex1.pex')
    builder1 = PEXBuilder(interpreter=interpreter, pex_info=pex_info1)
    add_requirements(builder1, cache)
    add_wheel(builder1, content1)
    add_sources(builder1, content2)
    builder1.build(pex1)

    pex_info2 = PexInfo.default()
    pex_info2.pex_path = pex1
    pex2 = os.path.join(root, 'pex2')
    builder2 = PEXBuilder(path=pex2, interpreter=interpreter, pex_info=pex_info2)
    add_requirements(builder2, cache)
    add_wheel(builder2, content3)
    builder2.set_script('foobaz')
    builder2.freeze()

    assert 42 == PEX(pex2, interpreter=interpreter).run(env=dict(PEX_VERBOSE='9'))


@pytest.fixture
def setuptools_requirement():
  # We use a very old version of setuptools to prove the point the user version is what is used
  # here and not the vendored version (when possible). A newer setuptools is needed though to work
  # with python 3.
  return 'setuptools==1.0' if PY2 else 'setuptools==17.0'


def test_issues_598_explicit_any_interpreter(setuptools_requirement):
  assert_force_local_implicit_ns_packages_issues_598(requirements=[setuptools_requirement],
                                                     create_ns_packages=True)


def test_issues_598_explicit_missing_requirement():
  assert_force_local_implicit_ns_packages_issues_598(create_ns_packages=True)


@pytest.fixture
def python_35_interpreter():
  # Python 3.5 supports implicit namespace packages.
  return PythonInterpreter.from_binary(ensure_python_interpreter(PY35))


def test_issues_598_implicit(python_35_interpreter):
  assert_force_local_implicit_ns_packages_issues_598(interpreter=python_35_interpreter,
                                                     create_ns_packages=False)


def test_issues_598_implicit_explicit_mixed(python_35_interpreter, setuptools_requirement):
  assert_force_local_implicit_ns_packages_issues_598(interpreter=python_35_interpreter,
                                                     requirements=[setuptools_requirement],
                                                     create_ns_packages=True)


def normalize(path):
  return os.path.normpath(os.path.realpath(path)).lower()


def test_write_zipped_internal_cache():
  # zip_safe pex will not be written to install cache unless always_write_cache
  with nested(yield_pex_builder(zip_safe=True), temporary_dir(), temporary_filename()) as (
      pb, pex_root, pex_file):

    pb.info.pex_root = pex_root
    pb.build(pex_file)

    existing, new, zip_safe = PEXEnvironment.write_zipped_internal_cache(pex_file, pb.info)
    assert len(zip_safe) == 1
    assert normalize(zip_safe[0].location).startswith(
        normalize(os.path.join(pex_file, pb.info.internal_cache))), (
            'loc: %s, cache: %s' % (
                normalize(zip_safe[0].location),
                normalize(os.path.join(pex_file, pb.info.internal_cache))))

    pb.info.always_write_cache = True
    existing, new, zip_safe = PEXEnvironment.write_zipped_internal_cache(pex_file, pb.info)
    assert len(new) == 1
    assert normalize(new[0].location).startswith(normalize(pb.info.install_cache))

    # Check that we can read from the cache
    existing, new, zip_safe = PEXEnvironment.write_zipped_internal_cache(pex_file, pb.info)
    assert len(existing) == 1
    assert normalize(existing[0].location).startswith(normalize(pb.info.install_cache))

  # non-zip_safe pex will be written to install cache
  with nested(yield_pex_builder(zip_safe=False), temporary_dir(), temporary_filename()) as (
      pb, pex_root, pex_file):

    pb.info.pex_root = pex_root
    pb.build(pex_file)

    existing, new, zip_safe = PEXEnvironment.write_zipped_internal_cache(pex_file, pb.info)
    assert len(new) == 1
    assert normalize(new[0].location).startswith(normalize(pb.info.install_cache))
    original_location = normalize(new[0].location)

    # do the second time to validate idempotence of caching
    existing, new, zip_safe = PEXEnvironment.write_zipped_internal_cache(pex_file, pb.info)
    assert len(existing) == 1
    assert normalize(existing[0].location) == original_location


def test_load_internal_cache_unzipped():
  # zip_safe pex will not be written to install cache unless always_write_cache
  with nested(yield_pex_builder(zip_safe=True), temporary_dir()) as (pb, pex_root):
    pb.info.pex_root = pex_root
    pb.freeze()

    dists = list(PEXEnvironment.load_internal_cache(pb.path(), pb.info))
    assert len(dists) == 1
    assert normalize(dists[0].location).startswith(
        normalize(os.path.join(pb.path(), pb.info.internal_cache)))


_KNOWN_BAD_APPLE_INTERPRETER = ('/System/Library/Frameworks/Python.framework/Versions/'
                                '2.7/Resources/Python.app/Contents/MacOS/Python')


@pytest.mark.skipif(not os.path.exists(_KNOWN_BAD_APPLE_INTERPRETER),
                    reason='Test requires known bad Apple interpreter {}'
                           .format(_KNOWN_BAD_APPLE_INTERPRETER))
def test_osx_platform_intel_issue_523():
  def bad_interpreter():
    return PythonInterpreter.from_binary(_KNOWN_BAD_APPLE_INTERPRETER)

  with temporary_dir() as cache:
    # We need to run the bad interpreter with a modern, non-Apple-Extras setuptools in order to
    # successfully install psutil; yield_pex_builder sets up the bad interpreter with our vendored
    # setuptools and wheel extras.
    with nested(yield_pex_builder(installer_impl=WheelInstaller, interpreter=bad_interpreter()),
                temporary_filename()) as (pb, pex_file):
      for resolved_dist in resolver.resolve(['psutil==5.4.3'],
                                            cache=cache,
                                            precedence=(SourcePackage, WheelPackage),
                                            interpreter=pb.interpreter):
        pb.add_dist_location(resolved_dist.distribution.location)
      pb.build(pex_file)

      # NB: We want PEX to find the bare bad interpreter at runtime.
      pex = PEX(pex_file, interpreter=bad_interpreter())

      def run(args, **env):
        pex_env = os.environ.copy()
        pex_env['PEX_VERBOSE'] = '1'
        pex_env.update(**env)
        process = pex.run(args=args,
                          env=pex_env,
                          blocking=False,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        return process.returncode, stdout, stderr

      returncode, _, stderr = run(['-c', 'import psutil'])
      assert 0 == returncode, (
        'Process failed with exit code {} and stderr:\n{}'.format(returncode, stderr)
      )

      returncode, stdout, stderr = run(['-c', 'import pkg_resources'])
      assert 0 != returncode, (
        'Isolated pex process succeeded but should not have found pkg-resources:\n'
        'STDOUT:\n'
        '{}\n'
        'STDERR:\n'
        '{}'
        .format(stdout, stdout, stderr)
      )

      returncode, stdout, stderr = run(
        ['-c', 'import pkg_resources; print(pkg_resources.get_supported_platform())'],
        # Let the bad interpreter site-packages setuptools leak in.
        PEX_INHERIT_PATH='1'
      )
      assert 0 == returncode, (
        'Process failed with exit code {} and stderr:\n{}'.format(returncode, stderr)
      )

      # Verify this worked along side the previously problematic pkg_resources-reported platform.
      release, _, _ = platform.mac_ver()
      major_minor = '.'.join(release.split('.')[:2])
      assert to_bytes('macosx-{}-intel'.format(major_minor)) == stdout.strip()


def test_activate_extras_issue_615():
  with yield_pex_builder() as pb:
    for resolved_dist in resolver.resolve(['pex[requests]==1.6.3'], interpreter=pb.interpreter):
      pb.add_requirement(resolved_dist.requirement)
      pb.add_dist_location(resolved_dist.distribution.location)
    pb.set_script('pex')
    pb.freeze()
    process = PEX(pb.path(), interpreter=pb.interpreter).run(args=['--version'],
                                                             env={'PEX_VERBOSE': '9'},
                                                             blocking=False,
                                                             stdout=subprocess.PIPE,
                                                             stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    assert 0 == process.returncode, (
      'Process failed with exit code {} and output:\n{}'.format(process.returncode, stderr)
    )
    assert to_bytes('{} 1.6.3'.format(os.path.basename(pb.path()))) == stdout.strip()
