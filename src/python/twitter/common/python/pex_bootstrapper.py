import contextlib
import os
import zipfile

__all__ = ('bootstrap_pex',)


def pex_info_name(entry_point):
  """Return the PEX-INFO for an entry_point"""
  return os.path.join(entry_point, 'PEX-INFO')


def is_compressed(entry_point):
  return os.path.exists(entry_point) and not os.path.exists(pex_info_name(entry_point))


def read_pexinfo_from_directory(entry_point):
  with open(pex_info_name(entry_point), 'rb') as fp:
    return fp.read()


def read_pexinfo_from_zip(entry_point):
  with contextlib.closing(zipfile.ZipFile(entry_point)) as zf:
    return zf.read('PEX-INFO')


def read_pex_info_content(entry_point):
  """Return the raw content of a PEX-INFO."""
  if is_compressed(entry_point):
    return read_pexinfo_from_zip(entry_point)
  else:
    return read_pexinfo_from_directory(entry_point)


def get_pex_info(entry_point):
  """Return the PexInfo object for an entry point."""
  from . import pex_info

  pex_info_content = read_pex_info_content(entry_point)
  if pex_info_content:
    return pex_info.PexInfo(pex_info_content)
  raise ValueError('Invalid entry_point: %s' % entry_point)


def needs_modified_importer(entry_point):
  return is_compressed(entry_point) and not get_pex_info(entry_point).always_write_cache


def bootstrap_pex(entry_point):
  if needs_modified_importer(entry_point):
    from . import importer
    importer.monkeypatch()
  from . import pex
  pex.PEX(entry_point).execute()
