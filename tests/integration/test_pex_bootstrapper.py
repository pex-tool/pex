# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
import os.path
import re
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.cache.dirs import CacheDir, InterpreterDir
from pex.common import safe_open
from pex.compatibility import commonpath
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import InterpreterConstraint
from pex.pex import PEX
from pex.pex_bootstrapper import ensure_venv
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from pex.venv.installer import CollisionError
from pex.venv.virtualenv import Virtualenv
from testing import PY38, PY39, PY_VER, ensure_python_interpreter, make_env, run_pex_command
from testing.pytest.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Any, List, Optional, Set, Text


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

    expected_venv_dir = PexInfo.from_pex(collisions_pex).runtime_venv_dir(collisions_pex)
    assert expected_venv_dir is not None

    full_hash1_dir = os.path.basename(os.path.dirname(expected_venv_dir))
    full_hash2_dir = os.path.basename(expected_venv_dir)

    venvs_dir = CacheDir.VENVS.path(pex_root=pex_root)
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
    assert 42 == subprocess.Popen(args=[venv_pex.pex], env=make_env(PEX_SCRIPT="pex")).wait()


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
        venv_dir = pex_info.runtime_venv_dir(nspkgs_pex)
        assert venv_dir is not None
        venv = Virtualenv(venv_dir=venv_dir)
        assert os.path.realpath(nspkgs_venv_pex.pex) == os.path.realpath(venv.join_path("pex"))
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
    assert os.path.realpath(CacheDir.INSTALLED_WHEELS.path(pex_root=pex_root)) == os.path.realpath(
        commonpath(list(package_file_installed_wheel_dirs))
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

        venv_dir = PexInfo.from_pex(pex_file).runtime_venv_dir(pex_file)
        assert venv_dir is not None
        venv = Virtualenv(venv_dir=venv_dir)
        pex_package = os.path.join(venv.site_packages_dir, "pex")
        assert os.path.isdir(pex_package)
        assert copies != os.path.islink(pex_package)

    assert_venv_site_packages_copies(copies=True)
    assert_venv_site_packages_copies(copies=False)


def test_boot_compatible_issue_1020_no_ic(tmpdir):
    # type: (Any) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(args=["psutil==5.9.0", "-o", pex]).assert_success()

    def assert_boot(python=None):
        # type: (Optional[str]) -> None
        args = [python] if python else []
        args.extend([pex, "-c", "import psutil, sys; print(sys.executable)"])
        output = subprocess.check_output(args=args, stderr=subprocess.PIPE)

        # N.B.: We expect the current interpreter the PEX was built with to be selected since the
        # PEX contains a single platform specific distribution that only works with that
        # interpreter. If the current interpreter is in a venv though, we expect the PEX bootstrap
        # to have broken out of the venv and used its base system interpreter.
        # See:
        #   https://github.com/pex-tool/pex/pull/1130
        #   https://github.com/pex-tool/pex/issues/1031
        assert (
            PythonInterpreter.get().resolve_base_interpreter()
            == PythonInterpreter.from_binary(
                str(output.decode("ascii").strip())
            ).resolve_base_interpreter()
        )

    assert_boot()
    assert_boot(sys.executable)

    other_interpreter = (
        ensure_python_interpreter(PY39) if PY_VER != (3, 9) else ensure_python_interpreter(PY38)
    )
    assert_boot(other_interpreter)


def test_boot_compatible_issue_1020_ic_min_compatible_build_time_hole(tmpdir):
    # type: (Any) -> None
    other_interpreter = PythonInterpreter.from_binary(
        ensure_python_interpreter(PY39) if PY_VER != (3, 9) else ensure_python_interpreter(PY38)
    )
    current_interpreter = PythonInterpreter.get()

    min_interpreter, max_interpreter = (
        (other_interpreter, current_interpreter)
        if other_interpreter.version < current_interpreter.version
        else (current_interpreter, other_interpreter)
    )
    assert min_interpreter.version < max_interpreter.version

    # Try to build a PEX that works for min and max, but only find max locally.
    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[
            "psutil==5.9.0",
            "-o",
            pex,
            "--python-path",
            max_interpreter.binary,
            "--interpreter-constraint",
            "{python}=={major}.{minor}.*".format(
                python=max_interpreter.identity.interpreter,
                major=min_interpreter.version[0],
                minor=min_interpreter.version[1],
            ),
            "--interpreter-constraint",
            "{python}=={major}.{minor}.*".format(
                python=max_interpreter.identity.interpreter,
                major=max_interpreter.version[0],
                minor=max_interpreter.version[1],
            ),
        ]
    ).assert_success()

    # Now try to run the PEX remotely where both min and max exist.
    output = subprocess.check_output(
        args=[min_interpreter.binary, pex, "-c", "import psutil, sys; print(sys.executable)"],
        env=make_env(
            PEX_PYTHON_PATH=os.pathsep.join((min_interpreter.binary, max_interpreter.binary))
        ),
        stderr=subprocess.PIPE,
    )

    # N.B.: We expect the max interpreter the PEX was built with to be selected since the
    # PEX contains a single platform specific distribution that only works with that
    # interpreter. If the max interpreter is in a venv though, we expect the PEX bootstrap
    # to have broken out of the venv and used its base system interpreter.
    # See:
    #   https://github.com/pex-tool/pex/pull/1130
    #   https://github.com/pex-tool/pex/issues/1031
    assert (
        max_interpreter.resolve_base_interpreter()
        == PythonInterpreter.from_binary(
            str(output.decode("ascii").strip())
        ).resolve_base_interpreter()
    )


def test_boot_resolve_fail(
    tmpdir,  # type: Any
    py38,  # type: PythonInterpreter
    py39,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(args=["--python", py38.binary, "psutil==5.9.0", "-o", pex]).assert_success()

    pex_python_path = os.pathsep.join((py39.binary, py310.binary))
    process = subprocess.Popen(
        args=[py39.binary, pex, "-c", ""],
        env=make_env(PEX_PYTHON_PATH=pex_python_path),
        stderr=subprocess.PIPE,
    )
    _, stderr = process.communicate()
    assert 0 != process.returncode
    error = stderr.decode("utf-8").strip()
    pattern = re.compile(
        r"^Failed to find compatible interpreter on path {pex_python_path}.\n"
        r"\n"
        r"Examined the following interpreters:\n"
        r"1\.\)\s+{py39_exe} {py39_req}\n"
        r"2\.\)\s+{py310_exe} {py310_req}\n"
        r"\n"
        r"No interpreter compatible with the requested constraints was found:\n"
        r"\n"
        r"  A distribution for psutil could not be resolved for {py39_exe}.\n"
        r"  Found 1 distribution for psutil that does not apply:\n"
        r"  1\.\) The wheel tags for psutil 5\.9\.0 are .+ which do not match the supported tags "
        r"of {py39_exe}:\n"
        r"  cp39-cp39-.+\n"
        r"  ... \d+ more ...\n"
        r"\n"
        r"  A distribution for psutil could not be resolved for {py310_exe}.\n"
        r"  Found 1 distribution for psutil that does not apply:\n"
        r"  1\.\) The wheel tags for psutil 5\.9\.0 are .+ which do not match the supported tags "
        r"of {py310_exe}:\n"
        r"  cp310-cp310-.+\n"
        r"  ... \d+ more ...".format(
            pex_python_path=re.escape(pex_python_path),
            py39_exe=py39.binary,
            py39_req=InterpreterConstraint.exact_version(py39),
            py310_exe=py310.binary,
            py310_req=InterpreterConstraint.exact_version(py310),
        ),
    )
    assert pattern.match(error), "Got error:\n{error}\n\nExpected pattern\n{pattern}".format(
        error=error, pattern=pattern.pattern
    )


def test_cached_venv_interpreter_paths(tmpdir):
    # type: (Tempdir) -> None

    # N.B.: Previously, the path ot the atomic_directory work dir would leak into various cached
    # paths in the PythonInterpreter INTERP-INFO files instead of the final resting path of the
    # atomically created venv.

    empty_pex = tmpdir.join("empty.pex")
    pex_root = tmpdir.join("pex_root")
    result = run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--venv",
            "--seed",
            "verbose",
            "-o",
            empty_pex,
        ]
    )
    result.assert_success()
    expected_prefix = os.path.dirname(json.loads(result.output)["pex"])

    actual_prefixes = []  # type: List[str]
    for interp_dir in InterpreterDir.iter_all(pex_root=pex_root):
        actual_prefixes.append(interp_dir.interpreter.prefix)

    assert expected_prefix in actual_prefixes, (
        "Expected venv prefix of {expected_prefix} not found in actual cached python interpreter "
        "prefixes:\n{actual_prefixes}".format(
            expected_prefix=expected_prefix, actual_prefixes="\n".join(actual_prefixes)
        )
    )
