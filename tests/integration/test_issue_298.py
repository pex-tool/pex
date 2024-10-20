# -*- coding: utf-8 -*-
# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import shutil
import subprocess
from textwrap import dedent

from pex.common import safe_open
from pex.fetcher import URLFetcher
from pex.typing import TYPE_CHECKING
from testing.docker import skip_unless_docker

if TYPE_CHECKING:
    from typing import Any


@skip_unless_docker
def test_confounding_encoding(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    sdists = os.path.join(str(tmpdir), "sdists")
    with safe_open(
        os.path.join(sdists, "CherryPy-7.1.0.zip"), "wb"
    ) as write_fp, URLFetcher().get_body_stream(
        "https://files.pythonhosted.org/packages/"
        "b7/dd/e95de2d7042bd53009e8673ca489effebd4a35d9b64b75ecfcca160efaf6/CherryPy-7.1.0.zip"
    ) as read_fp:
        shutil.copyfileobj(read_fp, write_fp)

    dest = os.path.join(str(tmpdir), "dest")
    subprocess.check_call(
        args=[
            "docker",
            "run",
            "--rm",
            "-v",
            "{code}:/code".format(code=pex_project_dir),
            "-w",
            "/code",
            "-v",
            "{sdists}:/sdists".format(sdists=sdists),
            "-v",
            "{dest}:/dest".format(dest=dest),
            "-e",
            "LANG=en_US.ISO-8859-1",
            "python:2.7-slim",
            "python2.7",
            "-c",
            dedent(
                """\
                from __future__ import absolute_import

                import atexit
                import os
                import zipfile

                from pex.common import open_zip


                def chown_dest():
                    for root, dirs, files in os.walk("/dest", topdown=False):
                        for path in dirs + files:
                            os.chown(os.path.join(root, path), {uid}, {gid})
                    os.chown("/dest", {uid}, {gid})


                atexit.register(chown_dest)

                with zipfile.ZipFile("/sdists/CherryPy-7.1.0.zip") as zf:
                    try:
                        zf.extractall("/dest")
                        raise AssertionError(
                            "Expected standard Python 2.7 ZipFile.extractall to fail."
                        )
                    except UnicodeEncodeError as e:
                        pass

                with open_zip("/sdists/CherryPy-7.1.0.zip") as zf:
                    zf.extractall("/dest")
                """.format(
                    uid=os.getuid(), gid=os.getgid()
                )
            ),
        ]
    )

    assert os.path.isfile(
        os.path.join(dest, "CherryPy-7.1.0", "cherrypy", "test", "static", "Слава Україні.html")
    )
