# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from textwrap import dedent

import pytest
from colors import yellow

from pex.common import safe_open, touch
from pex.testing import IS_PYPY3, make_env, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Iterable, List, Text


def create_pex(
    tmpdir,  # type: Any
    include_srcs=True,  # type: bool
    include_deps=True,  # type: bool
    extra_args=(),  # type: Iterable[str]
):
    pex_root = os.path.join(str(tmpdir), "pex_root")
    args = ["--pex-root", pex_root, "--runtime-pex-root", pex_root]

    if include_deps and include_srcs:
        name = "app.pex"
    elif include_deps:
        name = "deps.pex"
    elif include_srcs:
        name = "srcs.pex"
    else:
        name = "pex.file"
    pex_file = os.path.join(str(tmpdir), name)
    args.extend(["-o", pex_file])

    if include_srcs:
        src = os.path.join(str(tmpdir), "src")
        with safe_open(os.path.join(src, "app.py"), "w") as fp:
            fp.write(
                dedent(
                    """\
                    from __future__ import print_function

                    import sys

                    from colors import yellow

                    print(yellow("*** Flashy UI ***"), file=sys.stderr)
                    for entry in sys.path:
                        if not entry.startswith({unzipped_pexes_dir!r}):
                            print(entry)
                    """.format(
                        unzipped_pexes_dir=os.path.join(pex_root, "unzipped_pexes")
                    )
                )
            )
        args.extend(["-D", src, "-m", "app"])

    if include_deps:
        # N.B.: We use this particular version of ansicolors since it contains a top-level module:
        # colors.py. Some of the --venv symlink mode tests below only trigger for the exact case
        # of a distribution with no top level packages and just a top-level modules.
        args.append("ansicolors==1.0.2")

    run_pex_command(args=args + list(extra_args)).assert_success()
    return pex_file


def execute_app(
    pex_file,  # type: str
    **env  # type: str
):
    # type: (...) -> List[Text]

    process = subprocess.Popen(
        args=[pex_file], env=make_env(**env), stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = process.communicate()
    stripped_stderr = stderr.decode("utf-8").strip()
    assert 0 == process.returncode, stripped_stderr
    assert yellow("*** Flashy UI ***") in stripped_stderr
    return stdout.decode("utf-8").splitlines()


def test_pex_path_dedup(tmpdir):
    # type: (Any) -> None

    app = create_pex(tmpdir)
    expected_sys_path = execute_app(app)

    deps = create_pex(tmpdir, include_srcs=False)
    assert expected_sys_path == execute_app(app, PEX_PATH=deps)

    srcs = create_pex(tmpdir, include_deps=False)
    assert expected_sys_path == execute_app(app, PEX_PATH=os.pathsep.join((deps, srcs)))


@pytest.mark.parametrize(
    ["execution_mode_args"],
    [
        pytest.param([], id="zipapp"),
        pytest.param(["--venv", "--venv-site-packages-copies"], id="venv (site-packages copies)"),
        pytest.param(
            ["--venv", "--no-venv-site-packages-copies"],
            id="venv (site-packages symlinks)",
        ),
    ],
)
def test_pex_path_collision_non_conflicting(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    app = create_pex(tmpdir, extra_args=execution_mode_args)
    execute_app(app)

    # Test a non-conflicting duplicate dep collision.
    deps = create_pex(tmpdir, include_srcs=False)
    execute_app(app, PEX_PATH=deps)

    # Test a non-conflicting duplicate src collision.
    srcs = create_pex(tmpdir, include_deps=False)
    execute_app(app, PEX_PATH=os.pathsep.join((deps, srcs)))


def test_pex_path_collision_conflicting(tmpdir):
    # Test a conflicting duplicate dep top-level module collision.

    conflicting_colors = os.path.join(str(tmpdir), "conflicting_colors")
    touch(os.path.join(conflicting_colors, "colors.py"))
    with safe_open(os.path.join(conflicting_colors, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup

                setup(
                    name="conflicting-colors",
                    version="0.0.1",
                    py_modules=["colors"]
                )
                """
            )
        )
    alternate_colors = create_pex(
        tmpdir, include_srcs=False, include_deps=False, extra_args=[conflicting_colors]
    )
    env = make_env(PEX_PATH=alternate_colors)

    # A zipapp with a collision should always work, 1st on PEX_PATH wins.
    app = create_pex(tmpdir)
    execute_app(app, **env)

    def assert_venv_collision(*extra_args):
        # type: (*str) -> None

        app = create_pex(tmpdir, extra_args=["--venv"] + list(extra_args))
        process = subprocess.Popen(
            args=[app], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        _, stderr = process.communicate()
        decoded_stderr = stderr.decode("utf-8")

        # The --venv mode should warn about collisions but succeed.
        assert 0 == process.returncode, decoded_stderr
        assert "PEXWarning: Encountered collision building venv at " in decoded_stderr
        assert "site-packages/colors.py was provided by:" in decoded_stderr
        assert "sha1:17772af8295ffb7f4d6c3353665b5c542be332a2 -> " in decoded_stderr
        assert "sha1:da39a3ee5e6b4b0d3255bfef95601890afd80709 -> " in decoded_stderr

    assert_venv_collision("--venv-site-packages-copies")
    assert_venv_collision("--no-venv-site-packages-copies")
