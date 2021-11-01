# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import re

import pytest

from pex.pex import PEX
from pex.pex_bootstrapper import ensure_venv
from pex.pex_info import PexInfo
from pex.testing import run_pex_command
from pex.tools.commands.venv import CollisionError
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_ensure_venv(
    pex_src,  # type: str
    pex_bdist,  # type: str
    tmpdir,  # type: Any
):
    # type: (...) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")
    collisions_pex = os.path.join(str(tmpdir), "collisions.pex")
    run_pex_command(
        args=[
            pex_bdist,
            "-D",
            pex_src,
            "-o",
            collisions_pex,
            "--runtime-pex-root",
            pex_root,
            "--venv",
        ]
    ).assert_success()

    with pytest.raises(CollisionError):
        ensure_venv(PEX(collisions_pex), collisions_ok=False)

    # The directory structure for successfully executed --venv PEXes is:
    #
    # PEX_ROOT/
    #   venvs/
    #     s/  # shortcuts dir
    #       <short hash>/
    #         venv -> <real venv parent dir (see below)>
    #     <full hash1>/
    #       <full hash2>/
    #         <real venv>
    #
    # AtomicDirectory locks are used to create both branches of the venvs/ tree; so if there is a
    # failure creating a venv we expect just:
    #
    # PEX_ROOT/
    #   venvs/
    #     s/
    #       .<short hash>.atomic_directory.lck
    #     <full hash1>/
    #       .<full hash2>.atomic_directory.lck

    expected_venv_dir = PexInfo.from_pex(collisions_pex).venv_dir(collisions_pex)
    assert expected_venv_dir is not None

    full_hash1_dir = os.path.basename(os.path.dirname(expected_venv_dir))
    full_hash2_dir = os.path.basename(expected_venv_dir)

    venvs_dir = os.path.join(pex_root, "venvs")
    assert {"s", full_hash1_dir} == set(os.listdir(venvs_dir))
    short_listing = os.listdir(os.path.join(venvs_dir, "s"))
    assert 1 == len(short_listing)
    assert re.match(r"^\.[0-9a-f]+\.atomic_directory.lck", short_listing[0])
    assert [".{full_hash2}.atomic_directory.lck".format(full_hash2=full_hash2_dir)] == os.listdir(
        os.path.join(venvs_dir, full_hash1_dir)
    )
