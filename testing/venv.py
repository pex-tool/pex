# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

from pex.common import CopyMode
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    from typing import Iterable, Optional, Set


def assert_venv_site_packages_copy_mode(
    venv_dir,  # type: str
    expected_copy_mode,  # type: CopyMode.Value
    expected_files=None,  # type: Optional[Iterable[str]]
):
    # type: (...) -> None

    site_packages_files = set()  # type: Set[str]
    site_packages_dir = os.path.realpath(Virtualenv(venv_dir).site_packages_dir)
    for root, dirs, files in os.walk(site_packages_dir):
        # Metadata files are always copied for inscrutable historical reasons; so we skip
        # checking those.
        dirs[:] = [d for d in dirs if not d.endswith(".dist-info")]
        for f in files:
            if f == "PEX_EXTRA_SYS_PATH.pth":
                continue
            file_path = os.path.join(root, f)
            if expected_copy_mode is CopyMode.SYMLINK:
                assert os.path.islink(file_path)
            else:
                assert not os.path.islink(file_path)
                nlink = os.stat(file_path).st_nlink
                if expected_copy_mode is CopyMode.COPY:
                    assert 1 == nlink, "Expected {file} to have 1 link but found {nlink}".format(
                        file=file_path, nlink=nlink
                    )
                else:
                    assert (
                        nlink > 1
                    ), "Expected {file} to have more than 1 link but found {nlink}".format(
                        file=file_path, nlink=nlink
                    )
            site_packages_files.add(file_path)

    if expected_files:
        expected_files = set(os.path.join(site_packages_dir, f) for f in expected_files)
        assert expected_files == site_packages_files, (
            "Expected venv site-packages dir to contain these files:\n"
            "{expected_files}\n"
            "\n"
            "Found these files:\n"
            "{actual_files}"
        ).format(
            expected_files="\n".join(sorted(expected_files)),
            actual_files="\n".join(sorted(site_packages_files)),
        )
