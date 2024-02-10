# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

import pytest

from testing import run_pex_command


@pytest.mark.skipif(
    sys.version_info[:2] >= (3, 12),
    reason=(
        "There is an indirect urllib3 dependency which embeds six which uses a meta path importer "
        "that only implements the PEP-302 finder spec and not the modern spec. Only the modern "
        "finder spec is supported by Python 3.12+."
    ),
)
def test_pip_2020_resolver_engaged():
    # type: () -> None

    # The Pip legacy resolver cannot solve the following requirements but the 2020 resolver can.
    # Use this fact to prove we're plumbing Pip resolver version arguments correctly.
    pex_args = ["boto3==1.15.6", "botocore>1.17,<1.20", "--", "-c", "import boto3"]

    results = run_pex_command(args=["--resolver-version", "pip-legacy-resolver"] + pex_args)
    results.assert_failure()
    assert "Failed to resolve compatible distributions:" in results.error
    assert (
        "1: boto3==1.15.6 requires botocore<1.19.0,>=1.18.6 but botocore 1.19.63 was resolved"
        in results.error
    )

    run_pex_command(args=["--resolver-version", "pip-2020-resolver"] + pex_args).assert_success()
