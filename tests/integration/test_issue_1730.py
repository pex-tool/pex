# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os

import pytest

from pex.compatibility import url_quote
from pex.typing import TYPE_CHECKING
from testing import IS_PYPY, PY_VER, run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    PY_VER < (3, 7) or PY_VER >= (3, 10) or IS_PYPY,
    reason="Pants 2.12.0.dev3 requires Python >=3.7,<3.10 and does not publish a PyPy wheel.",
)
def test_check_install_issue_1730(
    tmpdir,  # type: Any
):
    # type: (...) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")
    constraints = os.path.join(str(tmpdir), "constraints.txt")
    with open(constraints, "w") as fp:
        print("packaging==21.3", file=fp)

    # The PyPI-hosted version of Pants 2.13.0.dev3 was deleted to make space available; so we use
    # the Pants S3 bucket instead.
    pants_hosted_version = "2.12.0.dev3+git552439fc"
    find_links = (
        "https://binaries.pantsbuild.org/wheels/pantsbuild.pants/"
        "552439fc4500284f97d09461d8f9a89df1ac1676/"
        "{pants_hosted_version}/"
        "index.html"
    ).format(pants_hosted_version=url_quote(pants_hosted_version))

    pex_args = [
        "--pex-root",
        pex_root,
        "--runtime-pex-root",
        pex_root,
        "--constraints",
        constraints,
        "-f",
        find_links,
        "pantsbuild.pants.testutil==2.12.0.dev3",
        "--",
        "-c",
        "from pants import testutil; print(testutil.__file__)",
    ]

    old_result = run_pex_command(args=["pex==2.1.81", "-c", "pex", "--"] + pex_args, quiet=True)
    old_result.assert_failure()
    assert (
        "Failed to resolve compatible distributions:\n"
        "1: pantsbuild.pants.testutil=={version} requires pantsbuild.pants=={version} but "
        "pantsbuild.pants {version} was resolved"
    ).format(version=pants_hosted_version) in old_result.error, old_result.error

    new_result = run_pex_command(args=pex_args, quiet=True)
    new_result.assert_success()
    assert new_result.output.startswith(pex_root)
