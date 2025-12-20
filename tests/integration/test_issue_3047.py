# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import re

from testing import run_pex_command


def test_verify_entry_point_with_no_entry_point():
    run_pex_command(args=["--validate-entry-point"], quiet=True).assert_failure(
        expected_error_re=r"^{msg}$".format(
            msg=re.escape(
                "You requested `--validate-entry-point` but specified no `--entry-point` to "
                "validate."
            )
        )
    )
