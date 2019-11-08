# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

from pex.pep425tags import get_supported


def distribution_compatible(dist, supported_tags=None):
  """Is this distribution compatible with the given supported tags?

  :param supported_tags: A list of tag tuples specifying which tags are supported
    by the platform in question; defaults to the current interpreter's supported tags.
  :returns: True if the distribution is compatible, False if it is unrecognized or incompatible.
  """
  if supported_tags is None:
    supported_tags = get_supported()

  filename, ext = os.path.splitext(os.path.basename(dist.location))
  if ext.lower() != '.whl':
    return False
  try:
    name_, raw_version_, py_tag, abi_tag, arch_tag = filename.rsplit('-', 4)
  except ValueError:
    return False

  def _iter_tags():
    for py in py_tag.split('.'):
      for abi in abi_tag.split('.'):
        for arch in arch_tag.split('.'):
          yield (py, abi, arch)

  return not frozenset(supported_tags).isdisjoint(frozenset(_iter_tags()))
