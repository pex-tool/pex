# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import filecmp
import glob
import os.path
import subprocess
import sys

import pytest

from pex.common import open_zip
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pip.installation import get_pip
from pex.resolve.resolver_configuration import BuildConfiguration
from pex.util import CacheHelper
from pex.wheel import Wheel
from testing import IS_PYPY, PY_VER, make_env, run_pex_command
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(
    IS_PYPY or PY_VER >= (3, 15),
    reason=(
        "This test requires a pre-built wheel to compare against an install, repack lifecycle and "
        "there are no pre-built wheels for PyPy or Python >=3.15."
    ),
)
@pytest.mark.parametrize(
    "use_system_time",
    [pytest.param(True, id="--use-system-time"), pytest.param(False, id="deterministic-default")],
)
def test_repository_extract_wheels_with_data(
    tmpdir,  # type: Tempdir
    use_system_time,  # type: bool
):
    # type: (...) -> None

    # N.B.: These two versions of greenlet are known to have wheels carrying
    # `greenlet-<version>.data/headers/greenlet.h` which stresses our round trip handling of the
    # strangest .data files case.

    greenlet_requirement = (
        "greenlet==1.1.2" if sys.version_info[:2] < (3, 11) else "greenlet==3.2.4"
    )

    wheels_dir = tmpdir.join("wheels")
    get_pip().spawn_download_distributions(
        download_dir=wheels_dir,
        requirements=[greenlet_requirement],
        build_configuration=BuildConfiguration.create(allow_builds=False),
        transitive=False,
    ).wait()

    downloaded_wheels = glob.glob(os.path.join(wheels_dir, "*.whl"))
    assert len(downloaded_wheels) == 1
    downloaded_greenlet_wheel = downloaded_wheels[0]

    pex = tmpdir.join("pex")
    run_pex_command(args=[greenlet_requirement, "--include-tools", "-o", pex]).assert_success()

    repo = tmpdir.join("repo")
    args = [pex, "repository", "extract", "-f", repo]
    if use_system_time:
        args.append("--use-system-time")
    subprocess.check_call(args=args, env=make_env(PEX_TOOLS=1, PEX_VERBOSE=1))
    extracted_wheels = glob.glob(os.path.join(repo, "*.whl"))
    assert len(extracted_wheels) == 1
    extracted_greenlet_wheel = extracted_wheels[0]

    assert os.path.basename(downloaded_greenlet_wheel) == os.path.basename(extracted_greenlet_wheel)
    assert use_system_time is filecmp.cmp(
        downloaded_greenlet_wheel, extracted_greenlet_wheel, shallow=False
    )

    downloaded_greenlet_unzipped = tmpdir.join(
        "{whl}.downloaded".format(whl=os.path.basename(downloaded_greenlet_wheel))
    )
    with open_zip(downloaded_greenlet_wheel) as zfp:
        zfp.extractall(downloaded_greenlet_unzipped)

    extracted_greenlet_unzipped = tmpdir.join(
        "{whl}.extracted".format(whl=os.path.basename(extracted_greenlet_wheel))
    )
    with open_zip(extracted_greenlet_wheel) as zfp:
        zfp.extractall(extracted_greenlet_unzipped)

    assert CacheHelper.dir_hash(downloaded_greenlet_unzipped) == CacheHelper.dir_hash(
        extracted_greenlet_unzipped
    )


def test_venv_repository_resolve_whls(tmpdir):
    # type: (Tempdir) -> None

    download_dir = tmpdir.join("wheels")
    get_pip().spawn_download_distributions(
        download_dir=download_dir, requirements=["ansicolors==1.1.8"]
    ).wait()
    pypi_wheels = glob.glob(os.path.join(download_dir, "*.whl"))
    assert len(pypi_wheels) == 1
    pypi_ansicolors_whl = pypi_wheels[0]
    ansicolors_wheel = Wheel.load(pypi_ansicolors_whl)
    assert ProjectName("ansicolors") == ansicolors_wheel.project_name
    assert Version("1.1.8") == ansicolors_wheel.version

    pex_root = tmpdir.join("pex-root")
    traditional_pex = tmpdir.join("pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "ansicolors==1.1.8",
            "-o",
            traditional_pex,
            "--include-tools",
        ]
    ).assert_success()

    venv = tmpdir.join("venv")
    subprocess.check_call(args=[traditional_pex, "venv", venv], env=make_env(PEX_TOOLS=1))
    embedded_whl_pex = tmpdir.join("whl.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "ansicolors",
            "--venv-repository",
            venv,
            "-o",
            embedded_whl_pex,
            "--no-pre-install-wheels",
            "--include-tools",
        ]
    ).assert_success()

    repo = tmpdir.join("repo")
    subprocess.check_call(
        args=[embedded_whl_pex, "repository", "extract", "-f", repo, "--use-system-time"],
        env=make_env(PEX_TOOLS=1),
    )
    repo_wheels = glob.glob(os.path.join(repo, "*.whl"))
    assert len(repo_wheels) == 1
    repacked_ansicolors_whl = repo_wheels[0]
    assert filecmp.cmp(pypi_ansicolors_whl, repacked_ansicolors_whl, shallow=False)
