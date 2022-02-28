# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import re
import subprocess
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.pex import PEX
from pex.pex_bootstrapper import ensure_venv
from pex.pex_info import PexInfo
from pex.testing import make_env, run_pex_command
from pex.typing import TYPE_CHECKING
from pex.venv.pex import CollisionError
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    from typing import Any, Set, Text


def test_ensure_venv_short_link(
    pex_bdist,  # type: str
    tmpdir,  # type: Any
):
    # type: (...) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")

    collision_src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(collision_src, "will_not_collide_module.py"), "w") as fp:
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
                    will_not_collide_module
                
                [options.entry_points]
                console_scripts =
                    pex = will_not_collide_module:verb
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
            "--runtime-pex-root",
            pex_root,
            "--venv",
        ]
    ).assert_success()

    with pytest.raises(CollisionError):
        ensure_venv(PEX(collisions_pex), collisions_ok=False)

    # The directory structure for successfully executed --venv PEXes is:
    #
    # PEX_ROOT/
    #   venvs/
    #     s/  # shortcuts dir
    #       <short hash>/
    #         venv -> <real venv parent dir (see below)>
    #     <full hash1>/
    #       <full hash2>/
    #         <real venv>
    #
    # AtomicDirectory locks are used to create both branches of the venvs/ tree; so if there is a
    # failure creating a venv we expect just:
    #
    # PEX_ROOT/
    #   venvs/
    #     s/
    #       .<short hash>.atomic_directory.lck
    #     <full hash1>/
    #       .<full hash2>.atomic_directory.lck

    expected_venv_dir = PexInfo.from_pex(collisions_pex).venv_dir(collisions_pex)
    assert expected_venv_dir is not None

    full_hash1_dir = os.path.basename(os.path.dirname(expected_venv_dir))
    full_hash2_dir = os.path.basename(expected_venv_dir)

    venvs_dir = os.path.join(pex_root, "venvs")
    assert {"s", full_hash1_dir} == set(os.listdir(venvs_dir))
    short_listing = os.listdir(os.path.join(venvs_dir, "s"))
    assert 1 == len(short_listing)
    assert re.match(r"^\.[0-9a-f]+\.atomic_directory.lck", short_listing[0])
    assert [".{full_hash2}.atomic_directory.lck".format(full_hash2=full_hash2_dir)] == os.listdir(
        os.path.join(venvs_dir, full_hash1_dir)
    )

    venv_pex = ensure_venv(PEX(collisions_pex), collisions_ok=True)
    # We happen to know built distributions are always ordered before downloaded wheels in PEXes
    # as a detail of how `pex/resolver.py` works.
    assert 42 == subprocess.Popen(args=[venv_pex], env=make_env(PEX_SCRIPT="pex")).wait()


def test_ensure_venv_namespace_packages(tmpdir):
    # type: (Any) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")

    # We know the twitter.common.metrics distributions depends on 4 other distributions contributing
    # to the twitter.common namespace package:
    # + twitter.common.exceptions
    # + twitter.common.decorators
    # + twitter.common.lang
    # + twitter.common.quantity
    def create_ns_pkg_pex(copies):
        # type: (bool) -> Virtualenv
        nspkgs_pex = os.path.join(
            str(tmpdir), "ns-pkgs-{style}.pex".format(style="copies" if copies else "symlinks")
        )
        run_pex_command(
            args=[
                "twitter.common.metrics==0.3.11",
                "-o",
                nspkgs_pex,
                "--runtime-pex-root",
                pex_root,
                "--venv",
                "--venv-site-packages-copies" if copies else "--no-venv-site-packages-copies",
            ]
        ).assert_success()
        nspkgs_venv_pex = ensure_venv(PEX(nspkgs_pex), collisions_ok=False)

        pex_info = PexInfo.from_pex(nspkgs_pex)
        venv_dir = pex_info.venv_dir(nspkgs_pex)
        assert venv_dir is not None
        venv = Virtualenv(venv_dir=venv_dir)
        assert os.path.realpath(nspkgs_venv_pex) == os.path.realpath(venv.join_path("pex"))
        return venv

    venv_copies = create_ns_pkg_pex(copies=True)
    assert not os.path.exists(os.path.join(venv_copies.site_packages_dir, "pex-ns-pkgs.pth"))

    venv_symlinks = create_ns_pkg_pex(copies=False)
    pex_ns_pkgs_pth = os.path.join(venv_symlinks.site_packages_dir, "pex-ns-pkgs.pth")
    assert os.path.isfile(pex_ns_pkgs_pth)
    with open(pex_ns_pkgs_pth) as fp:
        assert 4 == len(fp.readlines())

    expected_path_entries = [
        os.path.join(venv_symlinks.site_packages_dir, d)
        for d in ("", "pex-ns-pkgs/1", "pex-ns-pkgs/2", "pex-ns-pkgs/3", "pex-ns-pkgs/4")
    ]
    for d in expected_path_entries:
        assert os.path.islink(os.path.join(venv_symlinks.site_packages_dir, d, "twitter"))
        assert os.path.isdir(os.path.join(venv_symlinks.site_packages_dir, d, "twitter", "common"))

    def find_package_paths(venv):
        # type: (Virtualenv) -> Set[Text]
        return set(
            subprocess.check_output(
                args=[
                    venv.join_path("pex"),
                    "-c",
                    dedent(
                        """\
                        from __future__ import print_function
                        import os
    
                        from twitter.common import decorators, exceptions, lang, metrics, quantity
        
                        
                        for pkg in decorators, exceptions, lang, metrics, quantity:
                            # These are all packages; so __file__ looks like:
                            #   <sys.path entry>/twitter/common/<pkg>/__init__.pyc
                            print(os.path.realpath(os.path.dirname(os.path.dirname(pkg.__file__))))
                        """
                    ),
                ]
            )
            .decode("utf-8")
            .splitlines()
        )

    assert 1 == len(
        find_package_paths(venv_copies)
    ), "Expected 1 unique package path for a venv built from copies."

    symlink_package_paths = find_package_paths(venv_symlinks)
    assert 5 == len(symlink_package_paths), "Expected 5 unique package paths for symlinked venv."

    # We expect package paths like:
    #   .../twitter.common.foo-0.3.11.*.whl/twitter/common
    package_file_installed_wheel_dirs = {
        os.path.dirname(os.path.dirname(p)) for p in symlink_package_paths
    }
    assert os.path.realpath(os.path.join(pex_root, PexInfo.INSTALL_CACHE)) == os.path.realpath(
        os.path.commonprefix(list(package_file_installed_wheel_dirs))
    ), "Expected contributing wheel content to be symlinked from the installed wheel cache."
    assert {
        "twitter.common.{package}-0.3.11-py{py_major}-none-any.whl".format(
            package=p, py_major=venv_symlinks.interpreter.version[0]
        )
        for p in ("decorators", "exceptions", "lang", "metrics", "quantity")
    } == {
        os.path.basename(d) for d in package_file_installed_wheel_dirs
    }, "Expected 5 unique contributing wheels."


def test_ensure_venv_site_packages_copies(
    pex_bdist,  # type: str
    tmpdir,  # type: Any
):
    # type: (...) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")
    pex_file = os.path.join(str(tmpdir), "pex")

    def assert_venv_site_packages_copies(copies):
        # type: (bool) -> None
        run_pex_command(
            args=[
                pex_bdist,
                "-o",
                pex_file,
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--venv",
                "--venv-site-packages-copies" if copies else "--no-venv-site-packages-copies",
                "--seed",
            ]
        ).assert_success()

        venv_dir = PexInfo.from_pex(pex_file).venv_dir(pex_file)
        assert venv_dir is not None
        venv = Virtualenv(venv_dir=venv_dir)
        pex_package = os.path.join(venv.site_packages_dir, "pex")
        assert os.path.isdir(pex_package)
        assert copies != os.path.islink(pex_package)

    assert_venv_site_packages_copies(copies=True)
    assert_venv_site_packages_copies(copies=False)
