# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import hashlib
import os
import subprocess
import zipfile
from textwrap import dedent

import colors  # vendor:skip

from pex.common import open_zip, safe_open
from pex.dist_metadata import ProjectNameAndVersion
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper
from testing import run_pex_command

if TYPE_CHECKING:
    from typing import Any


def test_no_pre_install_wheels(tmpdir):
    # type: (Any) -> None

    pex = os.path.join(str(tmpdir), "pex")
    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "main.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import colors
                import cowsay


                cowsay.tux(colors.blue("Moo?"))
                """
            )
        )

    # N.B.: We choose ansicolors 1.1.8 since it works with all Pythons and has a universal wheel
    # published on PyPI and cowsay 5.0 since it also works with all Pythons and only has an sdist
    # published on PyPI. This combination ensures the resolve process can handle both building
    # wheels (cowsay stresses this) and using pre-existing ones (ansicolors stresses this).
    run_pex_command(
        args=[
            "ansicolors==1.1.8",
            "cowsay==5.0",
            "--no-pre-install-wheels",
            "-o",
            pex,
            "-D",
            src,
            "-m",
            "main",
        ]
    ).assert_success()

    assert colors.blue("Moo?") in subprocess.check_output(args=[pex]).decode("utf-8")

    pex_info = PexInfo.from_pex(pex)
    assert frozenset(
        (ProjectNameAndVersion("ansicolors", "1.1.8"), ProjectNameAndVersion("cowsay", "5.0"))
    ) == frozenset(ProjectNameAndVersion.from_filename(dist) for dist in pex_info.distributions)

    dist_dir = os.path.join(str(tmpdir), "dist_dir")
    os.mkdir(dist_dir)
    with open_zip(pex) as zfp:
        for known_file in (
            "__main__.py",
            "__pex__/__init__.py",
            "PEX-INFO",
            ".bootstrap/pex/pex.py",
            "main.py",
        ):
            assert (
                zipfile.ZIP_DEFLATED == zfp.getinfo(known_file).compress_type
            ), "Expected non-deps files to be stored with compression."

        for location, sha in pex_info.distributions.items():
            dist_relpath = os.path.join(pex_info.internal_cache, location)
            info = zfp.getinfo(dist_relpath)
            assert (
                zipfile.ZIP_STORED == info.compress_type
            ), "Expected raw .whl files to be stored without (re-)compression."

            zfp.extract(info, dist_dir)
            assert sha == CacheHelper.hash(
                os.path.join(dist_dir, dist_relpath), hasher=hashlib.sha256
            )
