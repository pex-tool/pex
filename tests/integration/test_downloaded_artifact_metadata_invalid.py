# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import sys
from textwrap import dedent

import pytest

from pex.cache.dirs import DownloadDir
from pex.resolve.lockfile.download_manager import DownloadedArtifact
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Dict


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 8),
    reason="Building Pex requires Python >= 3.8 to read pyproject.toml heterogeneous arrays.",
)
def test_locks_equivalent_round_trip(
    tmpdir,  # type: Tempdir
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    pex_management_req = "{pex_project_dir}[management]".format(pex_project_dir=pex_project_dir)

    requirements = tmpdir.join("requirements.txt")
    with open(requirements, "w") as fp:
        fp.write(
            dedent(
                """\
                # Stress the editable bit for directory packages as well as handling extras.
                -e {pex_management_req}

                # Stress VCS subdirectory handling as well as sdists and wheels (insta-science has
                # a fair number of transitive deps).
                git+https://github.com/SerialDev/sdev_py_utils.git@bd4d36a0#egg=sdev_logging_utils&subdirectory=sdev_logging_utils

                # Stress archive subdirectory handling.
                insta-science @ https://github.com/a-scie/science-installers/archive/refs/tags/python-v0.6.1.zip#subdirectory=python
                """.format(
                    pex_management_req=pex_management_req
                )
            )
        )
    pex_root = tmpdir.join("pex-root")
    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--pip-version",
        "latest-compatible",
        "--style",
        "sources",
        "-r",
        requirements,
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()

    pex = tmpdir.join("pex")
    run_pex_command(args=["--pex-root", pex_root, "--lock", lock, "-o", pex]).assert_success()

    def read_contents(path):
        # type: (str) -> bytes
        with open(path, "rb") as fp:
            return fp.read()

    metadata_files = {}  # type: Dict[str, bytes]
    for download_dir in DownloadDir.iter_all(pex_root=pex_root):
        metadata_filename = DownloadedArtifact.metadata_filename(download_dir)
        metadata_files[metadata_filename] = read_contents(metadata_filename)

    assert len(metadata_files) > 3, (
        "We should have at least 1 metadata file for each top level requirement and we rely on one "
        "of those requirements having at least 1 transitive dependency."
    )
    for metadata_file in metadata_files:
        os.unlink(metadata_file)

    pex = tmpdir.join("pex")
    run_pex_command(args=["--pex-root", pex_root, "--lock", lock, "-o", pex]).assert_success()

    for download_dir in DownloadDir.iter_all(pex_root=pex_root):
        metadata_filename = DownloadedArtifact.metadata_filename(download_dir)
        assert metadata_files.pop(metadata_filename) == read_contents(metadata_filename)
    assert (
        not metadata_files
    ), "We should have re-generated and validated all original metadata_files."
