# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys
from contextlib import contextmanager

from pex import third_party
from pex.common import temporary_dir
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import Dict, Iterator, Tuple


@contextmanager
def temporary_pex_root():
    # type: () -> Iterator[Tuple[str, Dict[str, str]]]
    with temporary_dir() as pex_root, ENV.patch(PEX_ROOT=os.path.realpath(pex_root)) as env:
        original_isolated = third_party._ISOLATED
        try:
            third_party._ISOLATED = None
            yield os.path.realpath(pex_root), env
        finally:
            third_party._ISOLATED = original_isolated


def test_isolated_pex_root():
    # type: () -> None
    with temporary_pex_root() as (pex_root, _):
        devendored_chroot = os.path.realpath(third_party.isolated().chroot_path)
        assert pex_root == os.path.commonprefix([pex_root, devendored_chroot])


def test_isolated_vendoring_constraints_omitted():
    # type: () -> None
    with temporary_pex_root() as (pex_root, _):
        devendored_chroot = os.path.realpath(third_party.isolated().chroot_path)
        assert [] == [
            os.path.join(root, file)
            for root, _, files in os.walk(devendored_chroot)
            for file in files
            if file == "constraints.txt"
        ]


def test_isolated_idempotent_inprocess():
    # type: () -> None
    with temporary_pex_root():
        result1 = third_party.isolated()
        result2 = third_party.isolated()
        assert result1.pex_hash == result2.pex_hash
        assert os.path.realpath(result1.chroot_path) == os.path.realpath(result2.chroot_path)


def test_isolated_idempotent_subprocess():
    # type: () -> None
    with temporary_pex_root() as (_, env):
        devendored_chroot = os.path.realpath(third_party.isolated().chroot_path)
        stdout = subprocess.check_output(
            args=[
                sys.executable,
                "-c",
                "from pex import third_party; print(third_party.isolated().chroot_path)",
            ],
            env=env,
        )
        assert devendored_chroot == os.path.realpath(stdout.decode("utf-8").strip())
