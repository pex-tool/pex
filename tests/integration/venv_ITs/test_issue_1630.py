# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os

from pex.cache.dirs import CacheDir
from pex.dist_metadata import Distribution
from pex.installed_wheel import InstalledWheel
from pex.interpreter import PythonInterpreter
from pex.pep_427 import reinstall_venv
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from testing import PY39, ensure_python_venv, run_pex_command, subprocess

if TYPE_CHECKING:
    from typing import Any, Container, List


def test_data_files(tmpdir):
    # type: (Any) -> None

    venv = ensure_python_venv(PY39, tmpdir=tmpdir)
    py39 = venv.interpreter.binary
    pip = venv.bin_path("pip")

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
        python=py39,
    ).assert_success()

    pex_info = PexInfo.from_pex(pex_file)
    assert 1 == len(pex_info.distributions)
    nbconvert_wheel_name, fingerprint = next(iter(pex_info.distributions.items()))
    nbconvert_dist = Distribution.load(
        CacheDir.INSTALLED_WHEELS.path(fingerprint, nbconvert_wheel_name, pex_root=pex_root)
    )

    pex_venv = Virtualenv.create(
        os.path.join(str(tmpdir), "pex.venv"), interpreter=PythonInterpreter.from_binary(py39)
    )
    installed = list(
        reinstall_venv(installed_wheel=InstalledWheel.load(nbconvert_dist.location), venv=pex_venv)
    )
    assert installed

    # Single out one known data file to check
    conf = pex_venv.join_path("share", "jupyter", "nbconvert", "templates", "asciidoc", "conf.json")
    with open(conf) as fp:
        assert {"base_template": "base", "mimetypes": {"text/asciidoc": True}} == json.load(fp)

    # Check the rest by showing the venv created by Pex has all the same files as that created by
    # Pip.
    subprocess.check_call(args=[pip, "install", "--no-deps", "--no-compile", "nbconvert==6.4.2"])
    subprocess.check_call(args=[pip, "uninstall", "-y", "setuptools", "wheel", "pip"])
    pip_venv = Virtualenv.enclosing(py39)
    assert pip_venv is not None

    def recursive_listing(
        venv,  # type: Virtualenv
        exclude=(),  # type: Container[str]
    ):
        # type: (...) -> List[str]
        return sorted(
            os.path.relpath(os.path.join(root, f), venv.venv_dir)
            for root, _, files in os.walk(venv.venv_dir)
            for f in files
            if f not in exclude
        )

    # We exclude the original-whl-info.json .pex-info metadata file since it's Pex-proprietary
    # metadata to support wheel round-tripping.
    assert recursive_listing(pip_venv) == recursive_listing(
        pex_venv, exclude=["original-whl-info.json"]
    )
