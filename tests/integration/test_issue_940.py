# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
from textwrap import dedent

import pytest

from pex.pip.version import PipVersion
from pex.typing import TYPE_CHECKING
from testing import built_wheel, run_pex_command, run_simple_pex

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    sys.version_info[:2] >= (3, 12) or PipVersion.DEFAULT >= PipVersion.v24_1,
    reason=(
        "We need to use setuptools<66 but Python 3.12+ require greater. We also need to avoid "
        "Pip>=24.1 which upgrades its vendored packaging to a version that rejects invalid "
        "versions"
    ),
)
def test_resolve_arbitrary_equality(tmpdir):
    # type: (Any) -> None

    def prepare_project(project_dir):
        # type: (str) -> None
        with open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
            fp.write(
                dedent(
                    """\
                    [build-system]
                    # Setuptools 66 removed support for PEP-440 non-compliant versions.
                    # See: https://setuptools.pypa.io/en/stable/history.html#v66-0-0
                    requires = ["setuptools<66"]
                    """
                )
            )

    with built_wheel(
        prepare_project=prepare_project,
        name="foo",
        version="1.0.2-fba4511",
        # We need this to allow the invalid version above to sneak by pip wheel metadata
        # verification.
        verify=False,
        python_requires=">=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*",
    ) as whl:
        pex_root = os.path.join(str(tmpdir), "pex_root")
        pex_file = os.path.join(str(tmpdir), "pex")
        run_pex_command(
            args=["-o", pex_file, "--pex-root", pex_root, "--runtime-pex-root", pex_root, whl]
        ).assert_success()

        output, returncode = run_simple_pex(pex_file, args=["-c", "import foo"])
        assert returncode == 0, output
        assert output == b""
