# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path
import subprocess

from pex import dist_metadata
from pex.dist_metadata import ProjectNameAndVersion
from pex.orderedset import OrderedSet
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from testing import run_pex_command

if TYPE_CHECKING:
    from typing import Any


def test_duplicate_requirements_issues_1550(tmpdir):
    # type: (Any) -> None

    pex_file = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[
            "PyJWT",
            "PyJWT==1.7.1",
            "--resolver-version",
            "pip-2020-resolver",
            "-o",
            pex_file,
        ]
    ).assert_success()

    subprocess.check_call(args=[pex_file, "-c", "import jwt"])
    pex_info = PexInfo.from_pex(pex_file)
    assert 1 == len(pex_info.distributions)
    assert ProjectNameAndVersion("PyJWT", "1.7.1") == dist_metadata.project_name_and_version(
        next(iter(pex_info.distributions.keys()))
    ), "ex_info.distributions: {}".format(pex_info.distributions)
    assert OrderedSet(("PyJWT", "PyJWT==1.7.1")) == pex_info.requirements
