# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

from pex.pex import PEX
from pex.testing import temporary_dir, write_simple_pex

# Tests that exercise interfaces in pex in the ways that pants would use them.

def test_pex_run_stdout_stderr_as_kwargs():
  # Used by pants' `python-eval` task.
  with temporary_dir() as temp_dir:
    pex = write_simple_pex(temp_dir, 'print("hello!")')
    PEX(pex.path()).run(stdout=sys.stdout, stderr=sys.stderr)
