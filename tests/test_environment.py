# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
import platform
import subprocess
from contextlib import contextmanager

import pytest
from twitter.common.contextutil import temporary_dir

from pex import resolver
from pex.compatibility import nested, to_bytes
from pex.environment import PEXEnvironment
from pex.installer import EggInstaller, WheelInstaller
from pex.interpreter import PythonInterpreter
from pex.package import EggPackage, SourcePackage, WheelPackage
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.testing import make_bdist, temporary_filename
from pex.version import SETUPTOOLS_REQUIREMENT, WHEEL_REQUIREMENT


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
  def bad_interpreter(include_site_extras=True):
    return PythonInterpreter.from_binary(_KNOWN_BAD_APPLE_INTERPRETER,
                                         include_site_extras=include_site_extras)

  interpreter = bad_interpreter(include_site_extras=False)
  with temporary_dir() as cache:
    # We need to run the bad interpreter with a modern, non-Apple-Extras setuptools in order to
    # successfully install psutil.
    for requirement in (SETUPTOOLS_REQUIREMENT, WHEEL_REQUIREMENT):
      for resolved_dist in resolver.resolve([requirement],
                                            cache=cache,
                                            # We can't use wheels since we're bootstrapping them.
                                            precedence=(SourcePackage, EggPackage),
                                            interpreter=interpreter):
        dist = resolved_dist.distribution
        interpreter = interpreter.with_extra(dist.key, dist.version, dist.location)

    with nested(yield_pex_builder(installer_impl=WheelInstaller, interpreter=interpreter),
                temporary_filename()) as (pb, pex_file):
      for resolved_dist in resolver.resolve(['psutil==5.4.3'],
                                            cache=cache,
                                            precedence=(SourcePackage, WheelPackage),
                                            interpreter=interpreter):
        pb.add_dist_location(resolved_dist.distribution.location)
      pb.build(pex_file)

      # NB: We want PEX to find the bare bad interpreter at runtime.
      pex = PEX(pex_file, interpreter=bad_interpreter())
      args = ['-c', 'import pkg_resources; print(pkg_resources.get_supported_platform())']
      env = os.environ.copy()
      env['PEX_VERBOSE'] = '1'
      process = pex.run(args=args,
                        env=env,
                        blocking=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
      stdout, stderr = process.communicate()
      assert 0 == process.returncode, (
        'Process failed with exit code {} and stderr:\n{}'.format(process.returncode, stderr)
      )

      # Verify this all worked under the previously problematic pkg_resources-reported platform.
      release, _, _ = platform.mac_ver()
      major_minor = '.'.join(release.split('.')[:2])
      assert to_bytes('macosx-{}-intel'.format(major_minor)) == stdout.strip()


def test_activate_extras_issue_615():
  with yield_pex_builder() as pb:
    for resolved_dist in resolver.resolve(['pex[requests]==1.5.1']):
      pb.add_requirement(resolved_dist.requirement)
      pb.add_dist_location(resolved_dist.distribution.location)
    pb.set_script('pex')
    pb.freeze()
    env = os.environ.copy()
    env['PEX_VERBOSE'] = '9'
    process = PEX(pb.path()).run(args=['--version'],
                                 env=env,
                                 blocking=False,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    assert 0 == process.returncode, (
      'Process failed with exit code {} and stderr:\n{}'.format(process.returncode, stderr)
    )
    assert to_bytes('{} 1.5.1'.format(os.path.basename(pb.path()))) == stdout.strip()
