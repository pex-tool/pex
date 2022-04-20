# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import sys
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 7),
    reason="The jaraco-collections 3.5.1 distribution requires Python >=3.7",
)
def test_check_install_issue_1726(tmpdir):
    # type: (Any) -> None

    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup

                setup(
                    name="pex-test",
                    version='0.1',
                    install_requires=[
                        "jaraco-collections==3.5.1",
                    ]
                )
                """
            )
        )

    pex_root = os.path.join(str(tmpdir), "pex_root")
    pex_args = [
        "--pex-root",
        pex_root,
        "--runtime-pex-root",
        pex_root,
        src,
        "--",
        "-c",
        "from jaraco import collections; print(collections.__file__)",
    ]
    old_result = run_pex_command(args=["pex==2.1.80", "-c", "pex", "--"] + pex_args)
    old_result.assert_failure()
    assert (
        "Failed to resolve compatible distributions:\n"
        "1: pex-test==0.1 requires jaraco-collections==3.5.1 but jaraco.collections 3.5.1 was "
        "resolved" in old_result.error
    )

    new_result = run_pex_command(args=pex_args)
    new_result.assert_success()
    assert new_result.output.startswith(pex_root)
