# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
from contextlib import closing, contextmanager
from textwrap import dedent
from typing import Mapping, Text

import colors  # vendor:skip
import pexpect  # type: ignore[import]  # MyPy can't see the types under Python 2.7.
import pytest
from colors import color  # vendor:skip

from pex.common import environment_as
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from pex.version import __version__
from testing import IS_PYPY, make_env, run_pex_command, scie

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, List, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def expect_banner_header(
    process,  # type: pexpect.spawn
    timeout,  # type: int
    expected_ephemeral,  # type: bool
    expected_suffix,  # type: str
    expect_color=True,  # type: bool
):
    # type: (...) -> None
    expected_banner_header = (
        "Pex {pex_version} {ephemeral}hermetic environment with {expected_suffix}".format(
            pex_version=__version__,
            ephemeral="ephemeral " if expected_ephemeral else "",
            expected_suffix=expected_suffix,
        )
    )
    if expect_color:
        expected_banner_header = color(
            expected_banner_header,
            fg="yellow",
            style="negative",
        )
    process.expect_exact(
        expected_banner_header.encode("utf-8"),
        # We extend the timeout to read the initial header line and even more so for PyPy, which is
        # slower to start up.
        timeout=timeout * (6 if IS_PYPY else 3),
    )


def expect_banner_footer(
    pex,  # type: Pex
    process,  # type: pexpect.spawn
    timeout,  # type: int
    expect_color=True,  # type: bool
):
    # type: (...) -> None

    for line in pex.expected_python_banner_lines:
        process.expect_exact(line, timeout=timeout)
    process.expect_exact(
        'Type "help", "{pex}", "copyright", "credits" or "license" for more '
        "information.".format(pex=colors.yellow("pex") if expect_color else "pex").encode("utf-8"),
        timeout=timeout,
    )
    process.expect_exact(b">>> ", timeout=timeout)


@attr.s(frozen=True)
class Pex(object):
    path = attr.ib()  # type: str
    expected_python_banner_lines = attr.ib()  # type: Tuple[Text, ...]

    def venv(self, venv_dir):
        # type: (str) -> Pex
        return Pex(
            path=os.path.join(venv_dir, "pex"),
            expected_python_banner_lines=self.expected_python_banner_lines,
        )


def create_pex(
    tmpdir,  # type: Any
    extra_args=(),  # type: Iterable[str]
):
    # type: (...) -> Pex
    pex = os.path.join(str(tmpdir), "pex")
    pex_root = os.path.join(str(tmpdir), "pex_root")
    run_pex_command(
        args=["--pex-root", pex_root, "--runtime-pex-root", pex_root, "-o", pex] + list(extra_args)
    ).assert_success()

    # N.B.: The sys.version can contain multiple lines for some distributions; so we split into
    # multiple lines here.
    expected_python_banner_lines = (
        subprocess.check_output(
            args=[
                os.path.join(pex, "__main__.py") if os.path.isdir(pex) else pex,
                "-c",
                dedent(
                    """\
                from __future__ import print_function

                import sys


                print(sys.version, "on", sys.platform)
                """
                ),
            ],
            env=make_env(PEX_INTERPRETER=1),
        )
        .decode("utf-8")
        .splitlines()
    )
    return Pex(path=pex, expected_python_banner_lines=tuple(expected_python_banner_lines))


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
    pex,  # type: Pex
    **kwargs  # type: Any
):
    # type: (...) -> Iterator[pexpect.spawn]
    with open(os.path.join(str(tmpdir), "pexpect.log"), "wb") as log:
        kwargs.update(dimensions=(24, 80), logfile=log)
        with closing(
            pexpect.spawn(
                os.path.join(pex.path, "__main__.py") if os.path.isdir(pex.path) else pex.path,
                **kwargs
            )
        ) as process:
            yield process


@attr.s(frozen=True)
class ColorConfig(object):
    @classmethod
    def create(
        cls,
        is_color,  # type: bool
        **kwargs  # type: str
    ):
        # type: (...) -> ColorConfig
        return cls(env=kwargs, is_color=is_color)

    _env = attr.ib()  # type: Mapping[str, str]
    _is_color = attr.ib()  # type: bool

    @contextmanager
    def env(self):
        # type: () -> Iterator[bool]
        with environment_as(**self._env):
            yield self._is_color


@execution_mode_args
@pytest.mark.parametrize(
    "scie_args",
    [pytest.param([], id="traditional")]
    + ([pytest.param(["--scie", "eager"], id="scie")] if scie.has_provider() else []),
)
@pytest.mark.parametrize(
    "color_config",
    [
        pytest.param(ColorConfig.create(is_color=True), id="IS_TTY"),
        pytest.param(ColorConfig.create(is_color=False, NO_COLOR="1"), id="NO_COLOR"),
        pytest.param(ColorConfig.create(is_color=False, TERM="dumb"), id="TERM=dumb"),
        pytest.param(
            ColorConfig.create(is_color=True, FORCE_COLOR="1", TERM="dumb"), id="FORCE_COLOR"
        ),
    ],
)
def test_empty_pex_no_args(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
    execution_mode_args,  # type: List[str]
    scie_args,  # type: List[str]
    color_config,  # type:ColorConfig
):
    # type: (...) -> None

    pex = create_pex(tmpdir, extra_args=execution_mode_args + scie_args)
    with color_config.env() as expect_color, pexpect_spawn(tmpdir, pex) as process:
        expect_banner_header(
            process,
            timeout=pexpect_timeout,
            expected_ephemeral=False,
            expected_suffix="no dependencies.",
            expect_color=expect_color,
        )
        expect_banner_footer(pex, process, timeout=pexpect_timeout, expect_color=expect_color)


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
        env=make_env(PATH=os.pathsep.join((os.path.dirname(pex.path), os.environ.get("PATH", "")))),
    ) as process:
        expect_banner_header(
            process,
            timeout=pexpect_timeout,
            expected_ephemeral=True,
            expected_suffix="no dependencies.",
        )
        process.expect_exact(
            colors.yellow(
                "Exit the repl (type quit()) and run `{pex} -h` for Pex CLI help.".format(
                    pex=os.path.basename(pex.path)
                )
            ).encode("utf-8")
        )
        expect_banner_footer(pex, process, timeout=pexpect_timeout)


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
            expected_ephemeral=False,
            expected_suffix="1 requirement and 1 activated distribution.",
        )
        expect_banner_footer(pex, process, timeout=pexpect_timeout)


@contextmanager
def expect_pex_info_response(
    tmpdir,  # type: Any
    pex,  # type: Pex
    timeout,  # type: int
    json=False,  # type: bool
):
    # type: (...) -> Iterator[pexpect.spawn]
    with pexpect_spawn(tmpdir, pex) as process:
        expect_banner_header(
            process, timeout=timeout, expected_ephemeral=False, expected_suffix="no dependencies."
        )
        expect_banner_footer(pex, process, timeout=timeout)
        process.sendline("pex(json={json!r})".format(json=json).encode("utf-8"))
        yield process


def test_pex_info_command_pex_file(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
):
    # type: (...) -> None
    pex = create_pex(tmpdir)
    with expect_pex_info_response(tmpdir, pex, pexpect_timeout) as process:
        process.expect_exact("Running from PEX file: {pex}".format(pex=pex.path).encode("utf-8"))


def test_pex_info_command_packed_pex_directory(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
):
    # type: (...) -> None
    pex = create_pex(tmpdir, extra_args=["--layout", "packed"])
    with expect_pex_info_response(tmpdir, pex, pexpect_timeout) as process:
        process.expect_exact(
            "Running from packed PEX directory: {pex}".format(pex=pex.path).encode("utf-8")
        )


def test_pex_info_command_venv_pex_file(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
):
    # type: (...) -> None
    pex = create_pex(tmpdir, extra_args=["--venv"])
    with expect_pex_info_response(tmpdir, pex, pexpect_timeout) as process:
        process.expect_exact(
            "Running from --venv PEX file: {pex}".format(pex=pex.path).encode("utf-8")
        )


def test_pex_info_command_loose_venv_pex_directory(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
):
    # type: (...) -> None
    pex = create_pex(tmpdir, extra_args=["--layout", "loose", "--venv"])
    with expect_pex_info_response(tmpdir, pex, pexpect_timeout) as process:
        process.expect_exact(
            "Running from loose --venv PEX directory: {pex}".format(pex=pex.path).encode("utf-8")
        )


def test_pex_info_command_pex_venv(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
):
    # type: (...) -> None
    pex = create_pex(tmpdir, extra_args=["--include-tools"])
    venv = os.path.join(str(tmpdir), "venv")
    subprocess.check_call(args=[pex.path, "venv", venv], env=make_env(PEX_TOOLS=1))
    with expect_pex_info_response(tmpdir, pex.venv(venv), pexpect_timeout) as process:
        process.expect_exact("Running in a PEX venv: {venv}".format(venv=venv).encode("utf-8"))


def test_pex_info_command_json(
    tmpdir,  # type: Any
    pexpect_timeout,  # type: int
):
    # type: (...) -> None
    pex = create_pex(tmpdir)
    with expect_pex_info_response(tmpdir, pex, pexpect_timeout, json=True) as process:
        for line in PexInfo.from_pex(pex.path).dump(indent=2).encode("utf-8").splitlines():
            process.expect_exact(line, timeout=pexpect_timeout)
