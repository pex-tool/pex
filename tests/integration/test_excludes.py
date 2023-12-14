# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
from os.path import commonprefix

import pytest

from pex.executor import Executor
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from testing import PY_VER, data, make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.fixture(scope="module")
def requests_certifi_excluded_pex(tmpdir_factory):
    # type: (Any) -> str

    requests_lock = data.path("locks", "requests.lock.json")
    pex_root = str(tmpdir_factory.mktemp("pex_root"))
    pex = str(tmpdir_factory.mktemp("pex"))
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

    return pex


REQUESTS_CMD = ["-c", "import requests, sys; print(sys.modules['certifi'].__file__)"]
EXPECTED_IMPORT_ERROR_MSG = "ModuleNotFoundError: No module named 'certifi'"


@pytest.fixture(scope="module")
def certifi_venv(tmpdir_factory):
    # type: (Any) -> Virtualenv

    venv = Virtualenv.create(venv_dir=str(tmpdir_factory.mktemp("venv")))
    pip = venv.install_pip()

    # N.B.: The constraining lock requirement is the one expressed by requests: certifi>=2017.4.17
    # The actual locked version is 2023.7.22; so we stress this crease and use a different, but
    # allowed, version.
    subprocess.check_call(args=[pip, "install", "certifi==2017.4.17"])

    return venv


skip_unless_37_to_312 = pytest.mark.skipif(
    PY_VER < (3, 7) or PY_VER >= (3, 13), reason="The lock used is for >=3.7,<3.13"
)


def assert_certifi_import_behavior(
    pex,  # type: str
    certifi_venv,  # type: Virtualenv
):
    requests_cmd = [pex] + REQUESTS_CMD

    # Although the venv has certifi available, a PEX is hermetic by default; so it shouldn't be
    # used.
    with pytest.raises(Executor.NonZeroExit) as exc:
        certifi_venv.interpreter.execute(args=requests_cmd)
    assert EXPECTED_IMPORT_ERROR_MSG in exc.value.stderr

    # Allowing the `sys.path` to be inherited should allow the certifi hole to be filled in.
    _, stdout, _ = certifi_venv.interpreter.execute(
        args=requests_cmd, env=make_env(PEX_INHERIT_PATH="fallback")
    )
    assert certifi_venv.site_packages_dir == commonprefix(
        [certifi_venv.site_packages_dir, stdout.strip()]
    )


@skip_unless_37_to_312
def test_exclude(
    tmpdir,  # type: Any
    requests_certifi_excluded_pex,  # type: str
    certifi_venv,  # type: Virtualenv
):
    # type: (...) -> None

    requests_cmd = [requests_certifi_excluded_pex] + REQUESTS_CMD

    # The exclude option is buyer beware. A PEX using this option will not work if the excluded
    # distributions carry modules that are, in fact, needed at run time.
    process = subprocess.Popen(args=requests_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, stderr = process.communicate()
    assert process.returncode != 0
    assert EXPECTED_IMPORT_ERROR_MSG in stderr.decode("utf-8"), stderr.decode("utf-8")

    assert_certifi_import_behavior(requests_certifi_excluded_pex, certifi_venv)


@skip_unless_37_to_312
def test_requirements_pex_exclude(
    tmpdir,  # type: Any
    requests_certifi_excluded_pex,  # type: str
    certifi_venv,  # type: Virtualenv
):
    # type: (...) -> None

    pex_root = PexInfo.from_pex(requests_certifi_excluded_pex).pex_root
    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[
            "--requirements-pex",
            requests_certifi_excluded_pex,
            "ansicolors==1.1.8",
            "-o",
            pex,
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
        ]
    ).assert_success()

    # Shouldn't need the certifi hole filled to import colors.
    output = subprocess.check_output(args=[pex, "-c", "import colors; print(colors.__file__)"])
    assert pex_root == commonprefix([pex_root, output.decode("utf-8").strip()])

    assert_certifi_import_behavior(pex, certifi_venv)
