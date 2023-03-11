# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path
import sys

import pytest

from pex.cli.testing import run_pex3
from pex.compatibility import commonpath
from pex.interpreter import PythonInterpreter
from pex.pex_info import PexInfo
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_vcs_respects_target(
    tmpdir,  # type: Any
    py38,  # type: PythonInterpreter
    py39,  # type: PythonInterpreter
):
    # type: (...) -> None

    lock = os.path.join(str(tmpdir), "lock.json")
    vcs_requirement = (
        "emote-rl[torch]@ "
        "git+https://github.com/EmbarkStudios/emote"
        "@4c5b31753e7a497fa57ab59e13344468510c920c"
        "#egg=emote-rl"
    )

    run_pex3(
        "lock",
        "create",
        "--style",
        "universal",
        "--resolver-version",
        "pip-2020-resolver",
        "--target-system",
        "linux",
        "--target-system",
        "mac",
        "--python-path",
        os.pathsep.join((py38.binary, py39.binary)),
        "--interpreter-constraint",
        "==3.9.*",
        vcs_requirement,
        "-o",
        lock,
        "--indent",
        "2",
    ).assert_success()

    pex = os.path.join(str(tmpdir), "pex")
    pex_root = os.path.join(str(tmpdir), "pex_root")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--lock",
            lock,
            "--python-path",
            os.pathsep.join((py38.binary, py39.binary)),
            "--interpreter-constraint",
            "==3.9.*",
            "--intransitive",
            vcs_requirement,
            "-o",
            pex,
        ],
        python=py38.binary,
    ).assert_success()

    assert {
        "emote_rl-23.0.0-py3-none-any.whl": (
            "e136042e61a0a4f6875cbfa06e4e3fada1f23f095364daf84c18d124fc4e462a"
        )
    } == PexInfo.from_pex(pex).distributions
