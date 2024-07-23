# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path

from pex.common import CopyMode
from pex.typing import TYPE_CHECKING
from testing.cli import run_pex3
from testing.venv import assert_venv_site_packages_copy_mode

if TYPE_CHECKING:
    from typing import Any


def test_venv_site_packages_copies(tmpdir):
    # type: (Any) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")
    expected_files = [
        os.path.join("cowsay", "__init__.py"),
        os.path.join("cowsay", "__main__.py"),
        os.path.join("cowsay", "characters.py"),
        os.path.join("cowsay", "main.py"),
        os.path.join("cowsay", "test.py"),
    ]

    venv = os.path.join(str(tmpdir), "venv")
    run_pex3("venv", "create", "--pex-root", pex_root, "-d", venv, "cowsay==5.0")
    assert_venv_site_packages_copy_mode(
        venv, expected_copy_mode=CopyMode.LINK, expected_files=expected_files
    )

    venv_copies = os.path.join(str(tmpdir), "venv-copies")
    run_pex3(
        "venv",
        "create",
        "--pex-root",
        pex_root,
        "-d",
        venv_copies,
        "cowsay==5.0",
        "--site-packages-copies",
    )
    assert_venv_site_packages_copy_mode(
        venv_copies, expected_copy_mode=CopyMode.COPY, expected_files=expected_files
    )
