# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
from os.path import commonprefix

import pytest

from pex.executor import Executor
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from testing import PY_VER, data, make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(PY_VER < (3, 7) or PY_VER >= (3, 13), reason="The lock used is for >=3.7,<3.13")
def test_exclude(tmpdir):
    # type: (Any) -> None

    requests_lock = data.path("locks", "requests.lock.json")
    pex_root = os.path.join(str(tmpdir), "pex_root")
    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[
            "--lock",
            requests_lock,
            "--exclude",
            "certifi",
            "-o",
            pex,
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
        ]
    ).assert_success()

    assert ProjectName("certifi") not in frozenset(
        dist.metadata.project_name for dist in PEX(pex).resolve()
    )

    # The exclude option is buyer beware. A PEX using this option will not work if the excluded
    # distributions carry modules that are, in fact, needed at run time.
    requests_cmd = [pex, "-c", "import requests, sys; print(sys.modules['certifi'].__file__)"]
    expected_import_error_msg = "ModuleNotFoundError: No module named 'certifi'"

    process = subprocess.Popen(args=requests_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, stderr = process.communicate()
    assert process.returncode != 0

    assert expected_import_error_msg in stderr.decode("utf-8"), stderr.decode("utf-8")

    venv_dir = os.path.join(str(tmpdir), "venv")
    venv = Virtualenv.create(venv_dir)
    pip = venv.install_pip()

    # N.B.: The constraining lock requirement is the one expressed by requests: certifi>=2017.4.17
    # The actual locked version is 2023.7.22; so we stress this crease and use a different, but
    # allowed, version.
    subprocess.check_call(args=[pip, "install", "certifi==2017.4.17"])

    # Although the venv has certifi available, a PEX is hermetic by default; so it shouldn't be
    # used.
    with pytest.raises(Executor.NonZeroExit) as exc:
        venv.interpreter.execute(args=requests_cmd)
    assert expected_import_error_msg in exc.value.stderr

    # Allowing the `sys.path` to be inherited should allow the certifi hole to be filled in.
    _, stdout, _ = venv.interpreter.execute(
        args=requests_cmd, env=make_env(PEX_INHERIT_PATH="fallback")
    )
    assert venv.site_packages_dir == commonprefix([venv.site_packages_dir, stdout.strip()])
