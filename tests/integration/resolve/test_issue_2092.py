# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path

from pex.interpreter import PythonInterpreter
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.cli import run_pex3

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

    # N.B.: It would be nice to assert the hash of the distribution here as well, but it uses:
    #
    #   [build-system]
    #   requires = ["pdm-pep517>=1.0.0"]
    #
    # This results in any new release of PDM breaking the expected hash since the WHEEL metadata
    # includes the PDM version:
    #
    #   $ unzip -qc emote_rl-23.0.0-py3-none-any.whl emote_rl-23.0.0.dist-info/WHEEL
    #   Wheel-Version: 1.0
    #   Generator: pdm-pep517 1.1.3
    #   Root-Is-Purelib: True
    #   Tag: py3-none-any
    #
    # Ideally, Pex could include lock information for each sdist in a lock that utilized PEP-518
    # and then use that information when building wheels from those locked sdists to form a PEX.
    # See: https://github.com/pex-tool/pex/issues/2100
    assert ["emote_rl-23.0.0-py3-none-any.whl"] == list(PexInfo.from_pex(pex).distributions)
