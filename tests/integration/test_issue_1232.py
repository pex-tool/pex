# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
import subprocess

from pex.cache.dirs import CacheDir
from pex.typing import TYPE_CHECKING
from testing import PY38, PY310, ensure_python_interpreter, make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any, Dict, FrozenSet, Iterator, List


def test_isolated_pex_zip(tmpdir):
    # type: (Any) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")

    python38 = ensure_python_interpreter(PY38)
    python310 = ensure_python_interpreter(PY310)

    pex_env = make_env(PEX_PYTHON_PATH=os.pathsep.join((python38, python310)))

    def add_pex_args(*args):
        # type: (*str) -> List[str]
        return list(args) + [
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--interpreter-constraint",
            "CPython=={version}".format(version=PY38),
        ]

    def tally_isolated_vendoreds():
        # type: () -> Dict[str, FrozenSet[str]]
        def vendored_toplevel(isolated_dir):
            # type: (str) -> Iterator[str]
            vendored_dir = os.path.join(isolated_dir, "pex/vendor/_vendored")
            for path in os.listdir(vendored_dir):
                if path in ("__pycache__", "__init__.py"):
                    continue
                if os.path.isdir(os.path.join(vendored_dir, path)):
                    yield path
                module, ext = os.path.splitext(path)
                if ext == ".py":
                    yield module

        isolated_root = CacheDir.ISOLATED.path(pex_root=pex_root)
        vendored_by_isolated = {}
        for entry in os.listdir(isolated_root):
            path = os.path.join(isolated_root, entry)
            if not os.path.isdir(path):
                continue
            vendored_by_isolated[path] = frozenset(vendored_toplevel(path))
        return vendored_by_isolated

    # 1. Isolate current loose source Pex at build-time.
    # ===
    current_pex_pex = os.path.join(str(tmpdir), "pex-current.pex")
    results = run_pex_command(
        args=add_pex_args(".", "-c", "pex", "-o", current_pex_pex), env=pex_env, python=python38
    )
    results.assert_success()

    current_isolated_vendoreds = tally_isolated_vendoreds()
    assert 1 == len(current_isolated_vendoreds), (
        "Since we just ran the Pex tool and nothing else, a single isolation of the Pex loose "
        "source in this repo should have occurred."
    )
    assert {"pip", "toml"}.issubset(
        list(current_isolated_vendoreds.values())[0]
    ), "Expected isolation of current Pex code to be a full build-time isolation."

    # 2. Isolate current Pex PEX at run-time.
    # ===
    modified_pex_src = os.path.join(str(tmpdir), "modified_pex_src")
    shutil.copytree("pex", os.path.join(modified_pex_src, "pex"))
    with open(os.path.join(modified_pex_src, "pex", "version.py"), "a") as fp:
        fp.write("# modified\n")
    # N.B.: Both the build-backend/, directory and the individual files copied below are used by
    # our PEP-517 build process.
    shutil.copytree("build-backend", os.path.join(modified_pex_src, "build-backend"))
    for build_file in (
        "LICENSE",
        "MANIFEST.in",
        "README.rst",
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
    ):
        shutil.copy(build_file, os.path.join(modified_pex_src, build_file))

    modified_pex = os.path.join(str(tmpdir), "modified.pex")
    subprocess.check_call(
        args=add_pex_args(
            python310, current_pex_pex, modified_pex_src, "-c", "pex", "-o", modified_pex
        ),
        env=pex_env,
    )
    current_pex_isolated_vendoreds = tally_isolated_vendoreds()
    current_pex_isolation = set(current_isolated_vendoreds.keys()) ^ set(
        current_pex_isolated_vendoreds.keys()
    )
    assert 0 == len(current_pex_isolation), (
        "Since the current Pex PEX was built from the same Pex code as the current loose source "
        "Pex, a new isolation of the Pex PEX bootstrap code should not have occurred."
    )

    # 3. Isolate modified Pex PEX at build-time.
    # ===
    ansicolors_pex = os.path.join(str(tmpdir), "ansicolors.pex")
    subprocess.check_call(
        args=add_pex_args(
            python310,
            modified_pex,
            "ansicolors==1.1.8",
            "-o",
            ansicolors_pex,
        ),
        env=pex_env,
    )
    modified_pex_isolated_vendoreds = tally_isolated_vendoreds()
    modified_pex_isolation = set(current_pex_isolated_vendoreds.keys()) ^ set(
        modified_pex_isolated_vendoreds.keys()
    )
    assert 1 == len(modified_pex_isolation), (
        "Since the ansicolors PEX was built from the modified Pex PEX a new isolation of the "
        "modified Pex PEX code should have occurred bringing the total isolations up to three."
    )
    assert {"pip", "toml"}.issubset(
        modified_pex_isolated_vendoreds[modified_pex_isolation.pop()]
    ), "Expected isolation of modified Pex code to be a full build-time isolation."

    # 4. Isolate modified Pex PEX at run-time.
    # ===
    # Force the bootstrap to run interpreter identification which will force a Pex isolation.
    shutil.rmtree(CacheDir.INTERPRETERS.path(pex_root=pex_root))
    subprocess.check_call(args=[python310, ansicolors_pex, "-c", "import colors"], env=pex_env)
    ansicolors_pex_isolated_vendoreds = tally_isolated_vendoreds()
    ansicolors_pex_isolation = set(modified_pex_isolated_vendoreds.keys()) ^ set(
        ansicolors_pex_isolated_vendoreds.keys()
    )
    assert 1 == len(ansicolors_pex_isolation), (
        "Since the ansicolors PEX has modified Pex bootstrap code, a further isolation should have"
        "occurred bringing the total isolations up to four."
    )
    ansicolors_pex_vendoreds = ansicolors_pex_isolated_vendoreds[ansicolors_pex_isolation.pop()]
    assert "pip" not in ansicolors_pex_vendoreds, "Expected a Pex runtime isolation."
    assert "toml" not in ansicolors_pex_vendoreds, "Expected a Pex runtime isolation."

    # 5. No new isolations.
    # ===
    ansicolors_pex = os.path.join(str(tmpdir), "ansicolors.old.pex")
    subprocess.check_call(
        args=add_pex_args(
            python310,
            modified_pex,
            "ansicolors==1.0.2",
            "-o",
            ansicolors_pex,
        ),
        env=pex_env,
    )

    # Force the bootstrap to run interpreter identification which will force a Pex isolation.
    shutil.rmtree(CacheDir.INTERPRETERS.path(pex_root=pex_root))
    subprocess.check_call(args=[python310, ansicolors_pex, "-c", "import colors"], env=pex_env)
    assert (
        ansicolors_pex_isolated_vendoreds == tally_isolated_vendoreds()
    ), "Expecting no new Pex isolations."
