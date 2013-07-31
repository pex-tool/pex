from twitter.common.python import pex_bootstrapper as pb

# 2.x/3.x mock import pattern
try:
  from unittest import mock
except ImportError:
  import mock


class AlwaysWriteCache(object):
  always_write_cache = True


class NeverWriteCache(object):
  always_write_cache = False


def test_needs_modified_importer():
  with mock.patch('twitter.common.python.pex_bootstrapper.is_compressed',
                  side_effect=lambda entry_point: entry_point == 'pex_file'):
    with mock.patch('twitter.common.python.pex_bootstrapper.get_pex_info') as get_pex_info:
      get_pex_info.side_effect = lambda entry_point: AlwaysWriteCache
      assert pb.needs_modified_importer('pex_file') is False
      assert pb.needs_modified_importer('dir') is False

      get_pex_info.side_effect = lambda entry_point: NeverWriteCache
      assert pb.needs_modified_importer('pex_file') is True
      assert pb.needs_modified_importer('dir') is False
