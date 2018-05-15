# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager
from optparse import OptionParser
from tempfile import NamedTemporaryFile

from twitter.common.contextutil import temporary_dir

from pex.bin.pex import build_pex, configure_clp, configure_clp_pex_resolution
from pex.common import safe_copy
from pex.compatibility import to_bytes
from pex.fetcher import Fetcher, PyPIFetcher
from pex.package import SourcePackage, WheelPackage
from pex.resolver_options import ResolverOptionsBuilder
from pex.sorter import Sorter
from pex.testing import make_sdist

try:
  from unittest import mock
except ImportError:
  import mock


@contextmanager
def parser_pair():
  builder = ResolverOptionsBuilder()
  parser = OptionParser()
  yield builder, parser


def test_clp_no_pypi_option():
  with parser_pair() as (builder, parser):
    configure_clp_pex_resolution(parser, builder)
    assert len(builder._fetchers) == 1
    options, _ = parser.parse_args(args=['--no-pypi'])
    assert len(builder._fetchers) == 0, '--no-pypi should remove fetchers.'
    assert options.repos == builder._fetchers


def test_clp_pypi_option_duplicate():
  with parser_pair() as (builder, parser):
    configure_clp_pex_resolution(parser, builder)
    assert len(builder._fetchers) == 1
    options, _ = parser.parse_args(args=['--pypi'])
    assert len(builder._fetchers) == 1
    assert options.repos == builder._fetchers


# TODO(wickman) We should probably add fetchers in order.
def test_clp_repo_option():
  with parser_pair() as (builder, parser):
    configure_clp_pex_resolution(parser, builder)
    assert len(builder._fetchers) == 1
    options, _ = parser.parse_args(args=['-f', 'http://www.example.com'])
    assert len(builder._fetchers) == 2
    assert builder._fetchers == options.repos


def test_clp_index_option():
  with parser_pair() as (builder, parser):
    configure_clp_pex_resolution(parser, builder)
    assert len(builder._fetchers) == 1
    options, _ = parser.parse_args(args=['-i', 'http://www.example.com'])
    assert len(builder._fetchers) == 2
    assert builder._fetchers == options.repos
    assert builder._fetchers[1] == PyPIFetcher('http://www.example.com')


def test_clp_build_precedence():
  with parser_pair() as (builder, parser):
    configure_clp_pex_resolution(parser, builder)
    assert builder._precedence == Sorter.DEFAULT_PACKAGE_PRECEDENCE

    parser.parse_args(args=['--no-build'])
    assert SourcePackage not in builder._precedence
    parser.parse_args(args=['--build'])
    assert SourcePackage in builder._precedence

    options, _ = parser.parse_args(args=['--no-wheel'])
    assert WheelPackage not in builder._precedence
    assert not options.use_wheel

    options, _ = parser.parse_args(args=['--wheel'])
    assert WheelPackage in builder._precedence
    assert options.use_wheel


# Make sure that we're doing append and not replace
def test_clp_requirements_txt():
  parser, builder = configure_clp()
  options, _ = parser.parse_args(args='-r requirements1.txt -r requirements2.txt'.split())
  assert options.requirement_files == ['requirements1.txt', 'requirements2.txt']


def test_clp_constraints_txt():
  parser, builder = configure_clp()
  options, _ = parser.parse_args(args='--constraint requirements1.txt'.split())
  assert options.constraint_files == ['requirements1.txt']


def test_clp_preamble_file():
  with NamedTemporaryFile() as tmpfile:
    tmpfile.write(to_bytes('print "foo!"'))
    tmpfile.flush()

    parser, resolver_options_builder = configure_clp()
    options, reqs = parser.parse_args(args=['--preamble-file', tmpfile.name])
    assert options.preamble_file == tmpfile.name

    pex_builder = build_pex(reqs, options, resolver_options_builder)
    assert pex_builder._preamble == to_bytes('print "foo!"')


def test_clp_prereleases():
  with parser_pair() as (builder, parser):
    configure_clp_pex_resolution(parser, builder)

    options, _ = parser.parse_args(args=[])
    assert not builder._allow_prereleases

    options, _ = parser.parse_args(args=['--no-pre'])
    assert not builder._allow_prereleases

    options, _ = parser.parse_args(args=['--pre'])
    assert builder._allow_prereleases


def test_clp_prereleases_resolver():
  prerelease_dep = make_sdist(name='dep', version='1.2.3b1')
  with temporary_dir() as td:
    safe_copy(prerelease_dep, os.path.join(td, os.path.basename(prerelease_dep)))
    fetcher = Fetcher([td])

    # When no specific options are specified, allow_prereleases is None
    parser, resolver_options_builder = configure_clp()
    assert resolver_options_builder._allow_prereleases is None

    # When we specify `--pre`, allow_prereleases is True
    options, reqs = parser.parse_args(args=['--pre', 'dep==1.2.3b1', 'dep'])
    assert resolver_options_builder._allow_prereleases
    # We need to use our own fetcher instead of PyPI
    resolver_options_builder._fetchers.insert(0, fetcher)

    #####
    # The resolver created during processing of command line options (configure_clp)
    # is not actually passed into the API call (resolve_multi) from build_pex().
    # Instead, resolve_multi() calls resolve() where a new ResolverOptionsBuilder instance
    # is created. The only way to supply our own fetcher to that new instance is to patch it
    # here in the test so that it can fetch our test package (dep-1.2.3b1). Hence, this class
    # below and the change in the `pex.resolver` module where the patched object resides.
    #
    import pex.resolver

    class BuilderWithFetcher(ResolverOptionsBuilder):
      def __init__(self,
                   fetchers=None,
                   allow_all_external=False,
                   allow_external=None,
                   allow_unverified=None,
                   allow_prereleases=None,
                   use_manylinux=None,
                   precedence=None,
                   context=None
                   ):
        super(BuilderWithFetcher, self).__init__(fetchers=fetchers,
                                                 allow_all_external=allow_all_external,
                                                 allow_external=allow_external,
                                                 allow_unverified=allow_unverified,
                                                 allow_prereleases=allow_prereleases,
                                                 use_manylinux=None,
                                                 precedence=precedence,
                                                 context=context)
        self._fetchers.insert(0, fetcher)
    # end stub
    #####

    # Without a corresponding fix in pex.py, this test failed for a dependency requirement of
    # dep==1.2.3b1 from one package and just dep (any version accepted) from another package.
    # The failure was an exit from build_pex() with the message:
    #
    # Could not satisfy all requirements for dep==1.2.3b1:
    #     dep==1.2.3b1, dep
    #
    # With a correct behavior the assert line is reached and pex_builder object created.
    with mock.patch.object(pex.resolver, 'ResolverOptionsBuilder', BuilderWithFetcher):
      pex_builder = build_pex(reqs, options, resolver_options_builder)
      assert pex_builder is not None
