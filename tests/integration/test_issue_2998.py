# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import filecmp
import glob
import os.path
import subprocess

from pex.common import open_zip, safe_rmtree
from pex.compatibility import commonpath
from pex.pip.installation import get_pip
from pex.resolve.resolver_configuration import BuildConfiguration
from pex.util import CacheHelper
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing import make_env, run_pex_command
from testing.pytest_utils.tmp import Tempdir


def test_record_directory_entries_handled(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")

    def assert_record_directory_entries_handled(*extra_args):
        # type: (*str) -> None
        safe_rmtree(pex_root)
        args = ["--pex-root", pex_root, "--runtime-pex-root", pex_root, "cmake==3.26.3"]
        args.extend(extra_args)
        args.append("--")
        args.append("-c")
        args.append("import cmake; print(cmake.__file__)")
        result = run_pex_command(args=args)
        result.assert_success()
        assert pex_root == commonpath((pex_root, result.output.strip()))

    assert_record_directory_entries_handled()
    assert_record_directory_entries_handled("--venv")


def test_record_directory_entries_whl_round_trip(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    download_dir = tmpdir.join("downloads")
    get_pip().spawn_download_distributions(
        download_dir=download_dir,
        requirements=["cmake==3.26.3"],
        build_configuration=BuildConfiguration.create(allow_builds=False),
    ).wait()

    original_wheels = glob.glob(os.path.join(download_dir, "*.whl"))
    assert len(original_wheels) == 1
    original_wheel = original_wheels[0]

    pex = tmpdir.join("pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "cmake==3.26.3",
            "--include-tools",
            "-o",
            pex,
        ]
    ).assert_success()

    extract_dir = tmpdir.join("extracted")
    subprocess.check_call(
        args=[pex, "repository", "extract", "-f", extract_dir, "--use-system-time"],
        env=make_env(PEX_TOOLS=1),
    )
    extracted_wheels = glob.glob(os.path.join(extract_dir, "*.whl"))
    assert len(extracted_wheels) == 1
    extracted_wheel = extracted_wheels[0]

    assert filecmp.cmp(original_wheel, extracted_wheel, shallow=False)

    venv_dir = tmpdir.join("venv")
    venv = Virtualenv.create(venv_dir=venv_dir, install_pip=InstallationChoice.UPGRADED)
    subprocess.check_call(args=[venv.interpreter.binary, "-m", "pip", "install", "cmake==3.26.3"])

    pex_from_venv = tmpdir.join("pex_from_venv")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--venv-repository",
            venv_dir,
            "cmake",
            "--include-tools",
            "-o",
            pex_from_venv,
        ]
    ).assert_success()
    extract_from_venv_dir = tmpdir.join("extracted-from-venv")
    subprocess.check_call(
        args=[
            pex_from_venv,
            "repository",
            "extract",
            "-f",
            extract_from_venv_dir,
        ],
        env=make_env(PEX_TOOLS=1),
    )
    extracted_from_venv_wheels = glob.glob(os.path.join(extract_from_venv_dir, "*.whl"))
    assert len(extracted_from_venv_wheels) == 1
    extracted_from_venv_wheel = extracted_from_venv_wheels[0]

    # N.B.: We compare extracted wheels mod RECORD since Pex did not install the original wheel in
    # the venv and record a cmake-3.26.3.pex-info/original-whl-info.json in the process. As such,
    # when Pex reconstitutes the whl, its RECORD entries are expected to have a different order.
    record_relpath = os.path.join("cmake-3.26.3.dist-info", "RECORD")

    unzipped_from_download_dir = os.path.join(download_dir, "unzipped")
    with open_zip(original_wheel) as zf:
        zf.extractall(unzipped_from_download_dir)
        os.unlink(os.path.join(unzipped_from_download_dir, record_relpath))

    unzipped_from_extract_from_venv_dir = os.path.join(extract_from_venv_dir, "unzipped")
    with open_zip(extracted_from_venv_wheel) as zf:
        zf.extractall(unzipped_from_extract_from_venv_dir)
        os.unlink(os.path.join(unzipped_from_extract_from_venv_dir, record_relpath))

    assert CacheHelper.dir_hash(unzipped_from_download_dir) == CacheHelper.dir_hash(
        unzipped_from_extract_from_venv_dir
    )
