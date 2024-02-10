# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path
import sys

import pytest

from pex.compatibility import commonpath
from pex.resolve.resolver_configuration import ResolverVersion
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 5),
    reason=(
        "This test relies on the python-forge 18.6.0 offering only the single "
        "python_forge-18.6.0-py35-none-any.whl distribution on PyPI and this wheel only works for "
        "Python 3.5 and greater"
    ),
)
@pytest.mark.parametrize(
    "resolver_version",
    [
        pytest.param(resolver_version, id=str(resolver_version))
        for resolver_version in ResolverVersion.values()
        if ResolverVersion.applies(resolver_version)
    ],
)
def test_abi_none_locking(
    tmpdir,  # type: Any
    resolver_version,  # type: ResolverVersion.Value
):
    # type: (...) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")
    lock = os.path.join(str(tmpdir), "lock.json")
    run_pex3(
        "lock",
        "create",
        "--style",
        "universal",
        "--resolver-version",
        str(resolver_version),
        "--interpreter-constraint",
        "==3.11.*",
        "python-forge==18.6.0",
        "-o",
        lock,
        "--indent",
        "2",
        "--pex-root",
        pex_root,
    ).assert_success()

    result = run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--lock",
            lock,
            "--",
            "-c",
            "import forge; print(forge.__file__)",
        ]
    )
    result.assert_success()
    assert pex_root == commonpath([pex_root, result.output.strip()])
