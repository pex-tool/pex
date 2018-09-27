# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager

from twitter.common.contextutil import temporary_dir

from pex.compatibility import nested
from pex.environment import PEXEnvironment
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.testing import make_bdist, temporary_filename


@contextmanager
def yield_pex_builder(zip_safe=True):
  with nested(temporary_dir(), make_bdist('p1', zipped=True, zip_safe=zip_safe)) as (td, p1):
    pb = PEXBuilder(path=td)
    pb.add_egg(p1.location)
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
