# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import subprocess

from pex.interpreter import PythonInterpreter
from pex.pep_376 import InstalledWheel
from pex.pex_info import PexInfo
from pex.testing import PY37, ensure_python_venv, run_pex_command
from pex.typing import TYPE_CHECKING
from pex.util import DistributionHelper
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    from typing import Any, List


def test_data_files(tmpdir):
    # type: (Any) -> None

    py37, pip = ensure_python_venv(PY37)

    pex_file = os.path.join(str(tmpdir), "pex.file")
    pex_root = os.path.join(str(tmpdir), "pex_root")
    run_pex_command(
        args=[
            "nbconvert==6.4.2",
            "--intransitive",
            "-o",
            pex_file,
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
        ],
        python=py37,
    ).assert_success()

    pex_info = PexInfo.from_pex(pex_file)
    assert 1 == len(pex_info.distributions)
    nbconvert_wheel_name, fingerprint = next(iter(pex_info.distributions.items()))
    nbconvert_dist = DistributionHelper.distribution_from_path(
        os.path.join(pex_info.install_cache, fingerprint, nbconvert_wheel_name)
    )
    assert nbconvert_dist is not None

    pex_venv = Virtualenv.create(
        os.path.join(str(tmpdir), "pex.venv"), interpreter=PythonInterpreter.from_binary(py37)
    )
    installed = list(InstalledWheel.load(nbconvert_dist.location).reinstall(pex_venv))
    assert installed

    # Single out one known data file to check
    conf = pex_venv.join_path("share", "jupyter", "nbconvert", "templates", "asciidoc", "conf.json")
    with open(conf) as fp:
        assert {"base_template": "base", "mimetypes": {"text/asciidoc": True}} == json.load(fp)

    # Check the rest by showing the venv created by Pex has all the same files as that created by
    # Pip.
    subprocess.check_call(args=[pip, "install", "--no-deps", "--no-compile", "nbconvert==6.4.2"])
    subprocess.check_call(args=[pip, "uninstall", "-y", "setuptools", "wheel", "pip"])
    pip_venv = Virtualenv.enclosing(py37)
    assert pip_venv is not None

    def recursive_listing(venv):
        # type: (Virtualenv) -> List[str]
        return sorted(
            os.path.relpath(os.path.join(root, f), venv.venv_dir)
            for root, _, files in os.walk(venv.venv_dir)
            for f in files
        )

    assert recursive_listing(pip_venv) == recursive_listing(pex_venv)
