# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import shutil
import subprocess

from pex.cache.dirs import CacheDir
from pex.common import safe_mkdir
from pex.compatibility import safe_commonpath
from pex.pip.version import PipVersion
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing import built_wheel, run_pex_command
from testing.pytest_utils.tmp import Tempdir


def test_extras_from_dup_root_reqs(tmpdir):
    # type: (Tempdir) -> None

    find_links = tmpdir.join("find-links")
    safe_mkdir(find_links)

    if PipVersion.DEFAULT is not PipVersion.VENDORED:
        Virtualenv.create(
            tmpdir.join("pip-resolver-venv"), install_pip=InstallationChoice.YES
        ).interpreter.execute(
            args=["-m", "pip", "wheel", "--wheel-dir", find_links]
            + list(map(str, PipVersion.DEFAULT.requirements))
        )

    with built_wheel(
        name="foo", extras_require={"bar": ["bar"], "baz": ["baz"]}
    ) as foo, built_wheel(name="bar") as bar, built_wheel(name="baz") as baz:
        shutil.copy(foo, find_links)
        shutil.copy(bar, find_links)
        shutil.copy(baz, find_links)

        pex_root = tmpdir.join("pex_root")
        pex = tmpdir.join("pex")
        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--no-pypi",
                "--find-links",
                find_links,
                "--resolver-version",
                "pip-2020-resolver",
                "foo[bar]",
                "foo[baz]",
                "-o",
                pex,
            ]
        ).assert_success()

        installed_wheel_dir = CacheDir.INSTALLED_WHEELS.path(pex_root=pex_root)
        for module in "foo", "bar", "baz":
            assert installed_wheel_dir == safe_commonpath(
                (
                    installed_wheel_dir,
                    subprocess.check_output(
                        args=[
                            pex,
                            "-c",
                            "import {module}; print({module}.__file__)".format(module=module),
                        ]
                    ).decode("utf-8"),
                )
            )
