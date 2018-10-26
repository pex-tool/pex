# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import os
import subprocess
import sys

from . import vendor_specs
from ..common import safe_delete, safe_rmtree


class VendorizeError(Exception):
  """Indicates an error was encountered updating vendored libraries."""


def vendorize(vendor_spec):
  cmd = ['pip', 'install', '--upgrade', '--no-compile', '--target', vendor_spec.target_dir,
         vendor_spec.requirement]
  result = subprocess.call(cmd)
  if result != 0:
    raise VendorizeError('Failed to vendor {!r}'.format(vendor_spec))

  # We know we can get these as a by-product of a pip install but never need them.
  safe_rmtree(os.path.join(vendor_spec.target_dir, 'bin'))
  safe_delete(os.path.join(vendor_spec.target_dir, 'easy_install.py'))


if __name__ == '__main__':
  if len(sys.argv) != 1:
    print('Usage: {}'.format(sys.argv[0]), file=sys.stderr)
    sys.exit(1)

  try:
    for vendor_spec in vendor_specs():
      vendorize(vendor_spec)
      print('Vendored {!r}.'.format(vendor_spec))
    sys.exit(0)
  except VendorizeError as e:
    print('Problem encountered vendorizing: {}'.format(e), file=sys.stderr)
    sys.exit(1)
