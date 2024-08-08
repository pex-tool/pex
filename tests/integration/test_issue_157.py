# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
import sys
from contextlib import closing, contextmanager

import pexpect  # type: ignore[import]  # MyPy can't see the types under Python 2.7.
import pytest
from colors import color  # vendor:skip

from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from pex.version import __version__
from testing import make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, List


EXPECTED_COLOR = dict(fg="yellow", style="negative")


def expect_banner_header(
    process,  # type: pexpect.spawn
    timeout,  # type: int
    expected_suffix,  # type: str
):
    # type: (...) -> None
    process.expect_exact(
        color(
            "Pex {pex_version} hermetic environment with {expected_suffix}".format(
                pex_version=__version__, expected_suffix=expected_suffix
            ),
            **EXPECTED_COLOR
        ).encode("utf-8"),
        timeout=timeout,
    )


def expect_banner_footer(
    process,  # type: pexpect.spawn
    timeout,  # type: int
):
    # type: (...) -> None

    # N.B.: The sys.version can contain multiple lines for some distributions; so we split here.
    for line in (
        "Python {python_version} on {platform}".format(
            python_version=sys.version, platform=sys.platform
        )
        .encode("utf-8")
        .splitlines()
    ):
        process.expect_exact(line, timeout=timeout)
    process.expect_exact(
        'Type "help", "{pex_info}", "copyright", "credits" or "license" for more '
        "information.".format(pex_info=color("pex_info", **EXPECTED_COLOR)).encode("utf-8"),
        timeout=timeout,
    )
    process.expect_exact(b">>> ", timeout=timeout)


def create_pex(
    tmpdir,  # type: Any
    extra_args=(),  # type: Iterable[str]
):
    # type: (...) -> str
    pex = os.path.join(str(tmpdir), "pex")
    pex_root = os.path.join(str(tmpdir), "pex_root")
    run_pex_command(
        args=["--pex-root", pex_root, "--runtime-pex-root", pex_root, "-o", pex]
        + list(extra_args)
        + ["--seed"]
    ).assert_success()
    return pex


execution_mode_args = pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--venv"], id="VENV"),
    ],
)


@contextmanager
def pexpect_spawn(
    tmpdir,  # type: Any
    *args,  # type: Any
    **kwargs  # type: Any
):
    # type: (...) -> Iterator[pexpect.spawn]
    with open(os.path.join(str(tmpdir), "pexpect.log"), "wb") as log:
        kwargs.update(dimensions=(24, 80), logfile=log)
        with closing(pexpect.spawn(*args, **kwargs)) as process:
            yield process


@execution_mode_args
def test_empty_pex_no_args(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex = create_pex(tmpdir, extra_args=execution_mode_args)
    with pexpect_spawn(tmpdir, pex) as process:
        expect_banner_header(process, timeout=pexpect_timeout, expected_suffix="no dependencies.")
        expect_banner_footer(process, timeout=pexpect_timeout)


@execution_mode_args
def test_pex_cli_no_args(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
    execution_mode_args,  # type: List[str]
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    pex = create_pex(tmpdir, extra_args=[pex_project_dir, "-c", "pex"] + execution_mode_args)
    with pexpect_spawn(
        tmpdir,
        pex,
        env=make_env(PATH=os.pathsep.join((os.path.dirname(pex), os.environ.get("PATH", "")))),
    ) as process:
        expect_banner_header(
            process,
            timeout=pexpect_timeout,
            expected_suffix="no dependencies. Run `{pex} -h` for Pex CLI help.".format(
                pex=os.path.basename(pex)
            ),
        )
        expect_banner_footer(process, timeout=pexpect_timeout)


@execution_mode_args
def test_pex_with_deps(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex = create_pex(tmpdir, extra_args=["ansicolors==1.1.8"] + execution_mode_args)
    with pexpect_spawn(tmpdir, pex) as process:
        expect_banner_header(
            process,
            timeout=pexpect_timeout,
            expected_suffix="1 requirement and 1 activated distribution.",
        )
        expect_banner_footer(process, timeout=pexpect_timeout)


@contextmanager
def expect_pex_info_response(
    tmpdir,  # type: Any
    pex,  # type: str
    timeout,  # type: int
    json=False,  # type: bool
):
    # type: (...) -> Iterator[pexpect.spawn]
    with pexpect_spawn(tmpdir, pex) as process:
        expect_banner_header(process, timeout=timeout, expected_suffix="no dependencies.")
        expect_banner_footer(process, timeout=timeout)
        process.sendline("pex_info(json={json!r})".format(json=json).encode("utf-8"))
        yield process


def test_pex_info_command_pex_file(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
):
    # type: (...) -> None
    pex = create_pex(tmpdir)
    with expect_pex_info_response(tmpdir, pex, pexpect_timeout) as process:
        process.expect_exact("Running from PEX file: {pex}".format(pex=pex).encode("utf-8"))


def test_pex_info_command_packed_pex_directory(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
):
    # type: (...) -> None
    pex = create_pex(tmpdir, extra_args=["--layout", "packed"])
    with expect_pex_info_response(
        tmpdir, os.path.join(pex, "__main__.py"), pexpect_timeout
    ) as process:
        process.expect_exact(
            "Running from packed PEX directory: {pex}".format(pex=pex).encode("utf-8")
        )


def test_pex_info_command_venv_pex_file(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
):
    # type: (...) -> None
    pex = create_pex(tmpdir, extra_args=["--venv"])
    with expect_pex_info_response(tmpdir, pex, pexpect_timeout) as process:
        process.expect_exact("Running from --venv PEX file: {pex}".format(pex=pex).encode("utf-8"))


def test_pex_info_command_loose_venv_pex_directory(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
):
    # type: (...) -> None
    pex = create_pex(tmpdir, extra_args=["--layout", "loose", "--venv"])
    with expect_pex_info_response(
        tmpdir, os.path.join(pex, "__main__.py"), pexpect_timeout
    ) as process:
        process.expect_exact(
            "Running from loose --venv PEX directory: {pex}".format(pex=pex).encode("utf-8")
        )


def test_pex_info_command_pex_venv(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
):
    # type: (...) -> None
    pex = create_pex(tmpdir, extra_args=["--include-tools"])
    venv = os.path.join(str(tmpdir), "venv")
    subprocess.check_call(args=[pex, "venv", venv], env=make_env(PEX_TOOLS=1))
    with expect_pex_info_response(tmpdir, os.path.join(venv, "pex"), pexpect_timeout) as process:
        process.expect_exact("Running in a PEX venv: {venv}".format(venv=venv).encode("utf-8"))


def test_pex_info_command_json(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
):
    # type: (...) -> None
    pex = create_pex(tmpdir)
    with expect_pex_info_response(tmpdir, pex, pexpect_timeout, json=True) as process:
        for line in PexInfo.from_pex(pex).dump(indent=2).encode("utf-8").splitlines():
            process.expect_exact(line, timeout=pexpect_timeout)
