# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess
from textwrap import dedent

from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    import colors  # vendor:skip
else:
    from pex.third_party import colors


def build_cyan_penguin_pex_assert_only_cowsay_built(
    tmpdir,  # type: Tempdir
    *extra_args  # type: str
):
    # type: (...) -> None

    with open(tmpdir.join("exe.py"), "w") as exe_fp:
        exe_fp.write(
            dedent(
                """\
                # /// script
                # dependencies = [
                #   "ansicolors",
                #   "cowsay<6",
                # ]
                # ///

                import sys

                import colors
                import cowsay


                cowsay.tux(colors.cyan(" ".join(sys.argv[1:])))
                """
            )
        )

    pex_root = tmpdir.join("pex-root")

    def build_pex_assert_only_cowsay_built(*more_args):
        # type: (*str) -> None

        pex = tmpdir.join("pex")
        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--exe",
                exe_fp.name,
                "-o",
                pex,
            ]
            + list(extra_args)
            + list(more_args)
        ).assert_success()

        assert "| {message} |".format(message=colors.cyan("Moo?")) in subprocess.check_output(
            args=[pex, "Moo?"]
        ).decode("utf-8")

    pip_log = tmpdir.join("pip.log")
    build_pex_assert_only_cowsay_built("--pip-log", pip_log)
    with open(pip_log) as fp:
        pip_source_log_lines = [line for line in fp if "Source in " in line]
    assert 1 == len(pip_source_log_lines), "Should have built 1 distribution."
    assert "which satisfies requirement cowsay<6" in pip_source_log_lines[0], pip_source_log_lines[
        0
    ]

    pex_lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--exe",
        exe_fp.name,
        "--indent",
        "2",
        "-o",
        pex_lock,
        *extra_args
    ).assert_success()
    build_pex_assert_only_cowsay_built("--lock", pex_lock)

    pylock = tmpdir.join("pylock.toml")
    run_pex3("lock", "export", "--format", "pep-751", pex_lock, "-o", pylock).assert_success()
    build_pex_assert_only_cowsay_built("--pylock", pylock)


def test_no_build_exception_allowed(tmpdir):
    # type: (Tempdir) -> None

    build_cyan_penguin_pex_assert_only_cowsay_built(tmpdir, "--no-build", "--only-build", "cowsay")


def test_no_wheel_exception_allowed(tmpdir):
    # type: (Tempdir) -> None

    # Under modern versions of Pip, setuptools may also be built from source as part of setting up
    # the PEP-517 build environment for cowsay; so we prevent this to avoid complications in the
    # assertion.
    build_cyan_penguin_pex_assert_only_cowsay_built(
        tmpdir, "--no-wheel", "--only-wheel", "ansicolors", "--only-wheel", "setuptools"
    )
