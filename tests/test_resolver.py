import os

from twitter.common.contextutil import temporary_dir

from pex.common import safe_copy
from pex.fetcher import Fetcher
from pex.resolver import resolve
from pex.testing import make_sdist


def test_thats_it_thats_the_test():
  empty_resolve = resolve([])
  assert empty_resolve == set()

  with temporary_dir() as td:
    empty_resolve = resolve([], cache=td)
    assert empty_resolve == set()


def test_simple_local_resolve():
  project_sdist = make_sdist(name='project')

  with temporary_dir() as td:
    safe_copy(project_sdist, os.path.join(td, os.path.basename(project_sdist)))
    fetchers = [Fetcher([td])]
    dists = resolve(['project'], fetchers=fetchers)
    assert len(dists) == 1


# TODO(wickman) Test resolve and cached resolve more directly than via
# integration.
