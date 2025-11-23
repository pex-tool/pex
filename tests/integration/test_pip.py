# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import re
import sys

import pytest

from testing import make_env, run_pex_command
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 9),
    reason="The adhoc Pip version used in the test requires Python>=3.9.",
)
def test_adhoc_nominal(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    pip_log = tmpdir.join("pip.log")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--pip-log",
            pip_log,
            "cowsay==5",
            "-c",
            "cowsay",
            "--",
            "Moo!",
        ],
        env=make_env(
            _PEX_PIP_VERSION="adhoc",
            # N.B.: This is a custom version of Pip that prints "Pex Adhoc Proof!" to STDERR just
            # before running the rest of Pip.
            _PEX_PIP_ADHOC_REQUIREMENT="pip @ git+https://github.com/pex-tool/pip@2c03ed1a2d60b57f",
        ),
    ).assert_success(
        expected_output_re=r"^.*{message}.*$".format(message=re.escape("| Moo! |")),
        re_flags=re.DOTALL | re.MULTILINE,
    )

    with open(pip_log) as fp:
        assert (
            "Pex Adhoc Proof!" in fp.read()
        ), "Expected proof we were running the right adhoc Pip version."


def test_adhoc_missing_req(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "cowsay==5",
            "-c",
            "cowsay",
            "--",
            "Moo!",
        ],
        env=make_env(_PEX_PIP_VERSION="adhoc", _PEX_PIP_ADHOC_REQUIREMENT=None),
    ).assert_failure(
        expected_error_re=r"^.*{message}.*$".format(
            message=re.escape(
                "You must set a value for the _PEX_PIP_ADHOC_REQUIREMENT environment variable to "
                "use an adhoc Pip version."
            )
        ),
        re_flags=re.DOTALL | re.MULTILINE,
    )
