# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re
import subprocess

import pytest

from pex.common import is_exe
from pex.layout import Layout
from pex.orderedset import OrderedSet
from pex.scie import SciePlatform, ScieStyle
from pex.targets import LocalInterpreter
from pex.typing import TYPE_CHECKING
from testing import IS_PYPY, PY_VER, make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any, Iterable, List


@pytest.mark.parametrize(
    "scie_style", [pytest.param(style, id=str(style)) for style in ScieStyle.values()]
)
@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=str(layout)) for layout in Layout.values()]
)
@pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--venv"], id="VENV"),
        pytest.param(["--sh-boot"], id="ZIPAPP-sh-boot"),
        pytest.param(["--venv", "--sh-boot"], id="VENV-sh-boot"),
    ],
)
def test_basic(
    tmpdir,  # type: Any
    scie_style,  # type: ScieStyle.Value
    layout,  # type: Layout.Value
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "cowsay.pex")
    result = run_pex_command(
        args=[
            "cowsay==5.0",
            "-c",
            "cowsay",
            "-o",
            pex,
            "--scie",
            str(scie_style),
            "--layout",
            str(layout),
        ]
        + execution_mode_args
    )
    if PY_VER < (3, 8) or IS_PYPY:
        result.assert_failure(
            expected_error_re=r".*^{message}$".format(
                message=re.escape(
                    "You selected `--scie {style}`, but none of the selected targets have "
                    "compatible interpreters that can be embedded to form a scie:\n"
                    "{target}".format(
                        style=scie_style, target=LocalInterpreter.create().render_description()
                    )
                )
            ),
            re_flags=re.DOTALL | re.MULTILINE,
        )
        return
    if PY_VER >= (3, 13):
        result.assert_failure(
            expected_error_re=(
                r".*"
                r"^Failed to build 1 scie:$"
                r".*"
                r"^Provider: No released assets found for release [0-9]{{8}} Python {version} "
                r"of flavor install_only\.$".format(version=".".join(map(str, PY_VER)))
            ),
            re_flags=re.DOTALL | re.MULTILINE,
        )
        return
    result.assert_success()

    scie = os.path.join(str(tmpdir), "cowsay")
    assert b"| PAR! |" in subprocess.check_output(args=[scie, "PAR!"], env=make_env(PATH=None))


def test_multiple_platforms(tmpdir):
    # type: (Any) -> None

    def create_scies(
        output_dir,  # type: str
        extra_args=(),  # type: Iterable[str]
    ):
        pex = os.path.join(output_dir, "cowsay.pex")
        run_pex_command(
            args=[
                "cowsay==5.0",
                "-c",
                "cowsay",
                "-o",
                pex,
                "--scie",
                "lazy",
                "--platform",
                "linux-aarch64-cp-39-cp39",
                "--platform",
                "linux-x86_64-cp-310-cp310",
                "--platform",
                "macosx-10.9-arm64-cp-311-cp311",
                "--platform",
                "macosx-10.9-x86_64-cp-312-cp312",
            ]
            + list(extra_args)
        ).assert_success()

    python_version_by_platform = {
        SciePlatform.LINUX_AARCH64: "3.9",
        SciePlatform.LINUX_X86_64: "3.10",
        SciePlatform.MACOS_AARCH64: "3.11",
        SciePlatform.MACOS_X86_64: "3.12",
    }
    assert SciePlatform.current() in python_version_by_platform

    def assert_platforms(
        output_dir,  # type: str
        expected_platforms,  # type: Iterable[SciePlatform.Value]
    ):
        # type: (...) -> None

        all_output_files = set(
            path
            for path in os.listdir(output_dir)
            if os.path.isfile(os.path.join(output_dir, path))
        )
        for platform in OrderedSet(expected_platforms):
            python_version = python_version_by_platform[platform]
            binary = platform.qualified_binary_name("cowsay")
            assert binary in all_output_files
            all_output_files.remove(binary)
            scie = os.path.join(output_dir, binary)
            assert is_exe(scie), "Expected --scie build to produce a {binary} binary.".format(
                binary=binary
            )
            if platform is SciePlatform.current():
                assert b"| PEX-scie wabbit! |" in subprocess.check_output(
                    args=[scie, "PEX-scie wabbit!"], env=make_env(PATH=None)
                )
                assert (
                    python_version
                    == subprocess.check_output(
                        args=[
                            scie,
                            "-c",
                            "import sys; print('.'.join(map(str, sys.version_info[:2])))",
                        ],
                        env=make_env(PEX_INTERPRETER=1),
                    )
                    .decode("utf-8")
                    .strip()
                )
        assert {"cowsay.pex"} == all_output_files, (
            "Expected one output scie for each platform plus the original cowsay.pex. All expected "
            "scies were found, but the remaining files are: {remaining_files}".format(
                remaining_files=all_output_files
            )
        )

    all_platforms_output_dir = os.path.join(str(tmpdir), "all-platforms")
    create_scies(output_dir=all_platforms_output_dir)
    assert_platforms(
        output_dir=all_platforms_output_dir,
        expected_platforms=(
            SciePlatform.LINUX_AARCH64,
            SciePlatform.LINUX_X86_64,
            SciePlatform.MACOS_AARCH64,
            SciePlatform.MACOS_X86_64,
        ),
    )

    # Now restrict the PEX's implied natural platform set of 4 down to 2 or 3 using
    # `--scie-platform`.
    restricted_platforms_output_dir = os.path.join(str(tmpdir), "restricted-platforms")
    create_scies(
        output_dir=restricted_platforms_output_dir,
        extra_args=[
            "--scie-platform",
            str(SciePlatform.current()),
            "--scie-platform",
            str(SciePlatform.LINUX_AARCH64),
            "--scie-platform",
            str(SciePlatform.LINUX_X86_64),
        ],
    )
    assert_platforms(
        output_dir=restricted_platforms_output_dir,
        expected_platforms=(
            SciePlatform.current(),
            SciePlatform.LINUX_AARCH64,
            SciePlatform.LINUX_X86_64,
        ),
    )
