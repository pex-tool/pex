# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
from textwrap import dedent

import pytest

from pex.pip.version import PipVersion
from pex.targets import LocalInterpreter
from testing import run_pex_command


@pytest.mark.skipif(
    sys.version_info[:2] >= (3, 12) or PipVersion.DEFAULT >= PipVersion.v23_2,
    reason=(
        "There is an indirect urllib3 dependency which embeds six which uses a meta path importer "
        "that only implements the PEP-302 finder spec and not the modern spec. Only the modern "
        "finder spec is supported by Python 3.12+. Also, Pip 23.2 dropped support for the legacy "
        "resolver, which this test needs."
    ),
)
def test_pip_2020_resolver_engaged():
    # type: () -> None

    # The Pip legacy resolver cannot solve the following requirements but the 2020 resolver can.
    # Use this fact to prove we're plumbing Pip resolver version arguments correctly.
    pex_args = ["boto3==1.15.6", "botocore>1.17,<1.20", "--", "-c", "import boto3"]

    results = run_pex_command(
        args=["--resolver-version", "pip-legacy-resolver"] + pex_args, quiet=True
    )
    results.assert_failure()
    assert (
        dedent(
            """\
            Failed to resolve compatible distributions for 1 target:
            1: {target} is not compatible with:
                boto3 1.15.6 requires botocore<1.19.0,>=1.18.6 but 1 incompatible dist was resolved:
                    botocore-1.19.63-py2.py3-none-any.whl
            """.format(
                target=LocalInterpreter.create().render_description()
            )
        )
        in results.error
    ), results.error
    run_pex_command(args=["--resolver-version", "pip-2020-resolver"] + pex_args).assert_success()
