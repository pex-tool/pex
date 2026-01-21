# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import filecmp
import subprocess

import pytest

from pex.dist_metadata import MetadataType
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from testing import make_env, run_pex_command
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import List


def test_round_trip(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")

    def create_cowsay_pex(
        pex_file,  # type: str
        *extra_args  # type: str
    ):
        # type: (...) -> str

        pex = tmpdir.join(pex_file)
        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "cowsay<6",
                "-c",
                "cowsay",
                "-o",
                pex,
                "--include-tools",
            ]
            + list(extra_args)
        ).assert_success()
        assert b"| Moo! |" in subprocess.check_output(args=[pex, "Moo!"])
        return pex

    from_requirements_pex = create_cowsay_pex("from-requirements.pex")

    venv = tmpdir.join("venv")
    subprocess.check_call(args=[from_requirements_pex, "venv", venv], env=make_env(PEX_TOOLS=1))

    from_venv_pex = create_cowsay_pex("from-venv.pex", "--venv-repository", venv)
    assert filecmp.cmp(from_requirements_pex, from_venv_pex, shallow=False)


@pytest.fixture
def non_dist_info_cowsay_venv(tmpdir):
    # type: (Tempdir) -> Virtualenv

    venv = Virtualenv.create(tmpdir.join("venv"))
    venv.ensure_pip()

    subprocess.check_call(
        args=[venv.interpreter.binary, "-m", "pip", "install", "cowsay<6", "--no-binary", "cowsay"]
    )
    dists_by_project_name = {
        dist.metadata.project_name: dist for dist in venv.iter_distributions(rescan=True)
    }
    cowsay_dist = dists_by_project_name[ProjectName("cowsay")]
    if cowsay_dist.metadata.type is MetadataType.DIST_INFO:
        pytest.skip(
            "The cowsay installation is .dist-info but the test requires a non .dist-info "
            "installation."
        )
    return venv


@pytest.mark.parametrize(
    "requirements",
    (
        pytest.param(["cowsay"], id="subset"),
        pytest.param([], id="full"),
    ),
)
def test_non_dist_info_handling(
    tmpdir,  # type: Tempdir
    non_dist_info_cowsay_venv,  # type: Virtualenv
    requirements,  # type: List[str]
):
    # type: (...) -> None

    pex = tmpdir.join("pex")
    run_pex_command(
        args=requirements
        + ["--venv-repository", non_dist_info_cowsay_venv.venv_dir, "-c", "cowsay", "-o", pex]
    ).assert_success()
    assert b"| Moo! |" in subprocess.check_output(args=[pex, "Moo!"])
    pex_project_names = {dist.metadata.project_name for dist in PEX(pex).resolve()}
    assert ProjectName("cowsay") in pex_project_names
    if requirements:
        assert ProjectName("pip") not in pex_project_names
    else:
        assert ProjectName("pip") in pex_project_names

    venv_dists_by_project_name = {
        dist.metadata.project_name: dist for dist in non_dist_info_cowsay_venv.iter_distributions()
    }
    assert (
        venv_dists_by_project_name[ProjectName("cowsay")].metadata.type
        is not MetadataType.DIST_INFO
    ), "Expected full resolve to handle mixed dist-info and non-dist-info"
    assert (
        venv_dists_by_project_name[ProjectName("pip")].metadata.type is MetadataType.DIST_INFO
    ), "Expected full resolve to handle mixed dist-info and non-dist-info"
