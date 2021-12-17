# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import shutil
import subprocess

import pytest

from pex.compatibility import PY3
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Callable, ContextManager, Tuple


@pytest.mark.skipif(
    condition=not PY3, reason="Test relies on a distribution that is Python 3 only."
)
def test_rel_cert_path(
    run_proxy,  # type: Callable[[], ContextManager[Tuple[int, str]]]
    tmpdir,  # type: Any
):
    # type: (...) -> None
    pex_file = os.path.join(str(tmpdir), "pex")
    with run_proxy() as (port, ca_cert):
        shutil.copy(ca_cert, "cert")
        run_pex_command(
            args=[
                "--proxy",
                "http://localhost:{port}".format(port=port),
                "--cert",
                "cert",
                "avro-python3==1.10.0",
                "-o",
                pex_file,
            ]
        ).assert_success()
        subprocess.check_call(args=[pex_file, "-c", "import avro"])
