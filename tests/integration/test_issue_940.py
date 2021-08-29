# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.common import temporary_dir
from pex.testing import built_wheel, run_pex_command, run_simple_pex


def test_resolve_arbitrary_equality():
    # type: () -> None
    with temporary_dir() as tmpdir, built_wheel(
        name="foo",
        version="1.0.2-fba4511",
        # We need this to allow the invalid version above to sneak by pip wheel metadata
        # verification.
        verify=False,
        python_requires=">=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*",
    ) as whl:
        pex_file = os.path.join(tmpdir, "pex")
        results = run_pex_command(args=["-o", pex_file, whl])
        results.assert_success()

        stdout, returncode = run_simple_pex(pex_file, args=["-c", "import foo"])
        assert returncode == 0
        assert stdout == b""
