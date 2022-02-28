# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys
from textwrap import dedent

from colors import cyan

from pex.common import filter_pyc_files, safe_open
from pex.testing import IntegResults, make_env, run_pex_command
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    from typing import Any, Set


def run_pex_tools(*args):
    # type: (*str) -> IntegResults

    process = subprocess.Popen(
        args=[sys.executable, "-mpex.tools"] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate()
    return IntegResults(
        output=stdout.decode("utf-8"), error=stderr.decode("utf-8"), return_code=process.returncode
    )


def test_collisions(
    tmpdir,  # type: Any
    pex_bdist,  # type: str
):
    # type: (...) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")

    collision_src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(collision_src, "will_not_collide_with_pex_module.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                def verb():
                  return 42
                """
            )
        )
    with safe_open(os.path.join(collision_src, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = collision
                version = 0.0.1

                [options]
                py_modules =
                    will_not_collide_with_pex_module
                
                [options.entry_points]
                # Although will_not_collide_with_pex_module does not collide with Pex, the 
                # generated bin/pex script will collide with the Pex pex script.
                console_scripts =
                    pex = will_not_collide_with_pex_module:verb
                """
            )
        )
    with safe_open(os.path.join(collision_src, "setup.py"), "w") as fp:
        fp.write("from setuptools import setup; setup()")

    collisions_pex = os.path.join(str(tmpdir), "collisions.pex")
    run_pex_command(
        args=[
            pex_bdist,
            collision_src,
            "-o",
            collisions_pex,
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
        ]
    ).assert_success()

    venv_dir = os.path.join(str(tmpdir), "collisions.venv")
    result = run_pex_tools(collisions_pex, "venv", venv_dir)
    result.assert_failure()
    assert (
        "CollisionError: Encountered collision building venv at {venv_dir} "
        "from {pex}:\n"
        "1. {venv_dir}/bin/pex was provided by:".format(venv_dir=venv_dir, pex=collisions_pex)
    ) in result.error

    result = run_pex_tools(collisions_pex, "venv", "--collisions-ok", "--force", venv_dir)
    result.assert_success()
    assert (
        "PEXWarning: Encountered collision building venv at {venv_dir} from {pex}:\n"
        "1. {venv_dir}/bin/pex was provided by:".format(venv_dir=venv_dir, pex=collisions_pex)
    ) in result.error
    assert 42 == subprocess.call(args=[Virtualenv(venv_dir=venv_dir).bin_path("pex")])


def test_collisions_mergeable_issue_1570(tmpdir):
    # type: (Any) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(args=["opencensus==0.8.0", "opencensus_context==0.1.2", "-o", pex])

    venv_dir = os.path.join(str(tmpdir), "venv")
    run_pex_tools(pex, "venv", venv_dir).assert_success()

    venv = Virtualenv(venv_dir=venv_dir)
    _, stdout, _ = venv.interpreter.execute(
        args=[
            "-c",
            dedent(
                """\
                from __future__ import print_function

                import opencensus
                import opencensus.common


                print(opencensus.__file__)
                print(opencensus.common.__file__)
                """
            ),
        ]
    )
    assert [
        os.path.join(venv.site_packages_dir, "opencensus", "__init__.py"),
        os.path.join(venv.site_packages_dir, "opencensus", "common", "__init__.py"),
    ] == stdout.splitlines()


def test_scope_issue_1631(tmpdir):
    # type: (Any) -> None

    src_dir = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src_dir, "app.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from colors import cyan

                print(cyan("Colluphid: Cupitt or Dawkins?"))
                """
            )
        )

    pex_root = os.path.join(str(tmpdir), "pex_root")
    app_pex = os.path.join(str(tmpdir), "app.pex")
    run_pex_command(
        args=[
            "-D",
            src_dir,
            "-m" "app",
            "ansicolors==1.1.8",
            "--include-tools",
            "-o",
            app_pex,
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
        ]
    ).assert_success()

    def execute_venv_tool(
        venv_dir,  # type: str
        *args  # type: str
    ):
        # type: (...) -> None
        subprocess.check_call(
            args=[app_pex, "venv", venv_dir] + list(args), env=make_env(PEX_TOOLS=1)
        )

    def assert_app(venv_dir):
        # type: (str) -> Virtualenv
        assert (
            cyan("Colluphid: Cupitt or Dawkins?")
            == subprocess.check_output(args=[os.path.join(venv_dir, "pex")]).decode("utf-8").strip()
        )
        return Virtualenv(venv_dir)

    def recursive_listing(venv_dir):
        # type: (str) -> Set[str]
        return {
            os.path.relpath(os.path.join(root, f), venv_dir)
            for root, _, files in os.walk(venv_dir)
            for f in filter_pyc_files(files)
        }

    def site_packages_path(
        venv_dir,  # type: str
        *relpath  # type: str
    ):
        # type: (...) -> str
        venv = Virtualenv(venv_dir)
        return os.path.relpath(os.path.join(venv.site_packages_dir, *relpath), venv.venv_dir)

    def app_py_path(venv_dir):
        # type: (str) -> str
        return site_packages_path(venv_dir, "app.py")

    def colors_package_path(venv_dir):
        # type: (str) -> str
        return site_packages_path(venv_dir, "colors", "__init__.py")

    venv_directory = os.path.join(str(tmpdir), "venv")
    execute_venv_tool(venv_directory)
    canonical_venv_listing = recursive_listing(venv_directory)
    venv = assert_app(venv_directory)
    # N.B.: Some venv activation scripts in bin/ differ since they hard code the venv python
    # interpreter path in them. Since we have a full canonical_venv_listing to check, we settle on
    # testing contents are identical just for site-packages which is what is important anyhow: it's
    # where the deps and user code are installed to.
    canonical_venv_hash = CacheHelper.dir_hash(venv.site_packages_dir)

    # 1st populate dependencies, then sources.
    venv_directory = os.path.join(str(tmpdir), "venv.deps-srcs")
    execute_venv_tool(venv_directory, "--scope=deps")
    colors_package = colors_package_path(venv_directory)
    app_module = app_py_path(venv_directory)

    assert colors_package in recursive_listing(venv_directory)
    assert app_module not in recursive_listing(venv_directory)

    execute_venv_tool(venv_directory, "--scope=srcs")
    assert colors_package in recursive_listing(venv_directory)
    assert app_module in recursive_listing(venv_directory)

    assert canonical_venv_listing == recursive_listing(venv_directory)
    venv = assert_app(venv_directory)
    assert canonical_venv_hash == CacheHelper.dir_hash(venv.site_packages_dir)

    # 1st populate sources, then dependencies.
    venv_directory = os.path.join(str(tmpdir), "venv.srcs-deps")
    execute_venv_tool(venv_directory, "--scope=srcs")
    colors_package = colors_package_path(venv_directory)
    app_module = app_py_path(venv_directory)

    assert app_module in recursive_listing(venv_directory)
    assert colors_package not in recursive_listing(venv_directory)

    execute_venv_tool(venv_directory, "--scope=deps")
    assert app_module in recursive_listing(venv_directory)
    assert colors_package in recursive_listing(venv_directory)

    assert canonical_venv_listing == recursive_listing(venv_directory)
    venv = assert_app(venv_directory)
    assert canonical_venv_hash == CacheHelper.dir_hash(venv.site_packages_dir)
