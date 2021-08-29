# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.testing import run_pex_command


def test_pip_2020_resolver_engaged():
    # type: () -> None

    # The Pip legacy resolver cannot solve the following requirements but the 2020 resolver can.
    # Use this fact to prove we're plumbing Pip resolver version arguments correctly.
    pex_args = ["boto3==1.15.6", "botocore>1.17<1.18.7", "--", "-c", "import boto3"]

    results = run_pex_command(args=["--resolver-version", "pip-legacy-resolver"] + pex_args)
    results.assert_failure()
    assert "Failed to resolve compatible distributions:" in results.error
    assert "1: boto3==1.15.6 requires botocore<1.19.0,>=1.18.6 but " in results.error

    run_pex_command(args=["--resolver-version", "pip-2020-resolver"] + pex_args).assert_success()
