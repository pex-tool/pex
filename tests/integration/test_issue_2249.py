# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess
from contextlib import closing
from textwrap import dedent
from typing import Iterator

import colors  # vendor:skip
import pexpect  # type: ignore[import]  # MyPy can't see the types under Python 2.7.
import pytest

from pex.common import safe_rmtree
from pex.typing import TYPE_CHECKING
from testing import IS_PYPY, make_env, run_pex_command, scie

if TYPE_CHECKING:
    from typing import Any, List


def _scie_args():
    # type: () -> Iterator[Any]
    yield pytest.param([], id="PEX")
    if scie.has_provider():
        yield pytest.param(["--scie", "eager"], id="SCIE")


@pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--sh-boot"], id="SH_BOOT"),
        pytest.param(["--venv"], id="VENV"),
        pytest.param(["--venv", "--sh-boot"], id="VENV-SH_BOOT"),
    ],
)
@pytest.mark.parametrize("scie_args", list(_scie_args()))
def test_inspect(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
    scie_args,  # type: List[str]
    pexpect_timeout,  # type: int
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=["ansicolors==1.1.8", "-o", pex] + execution_mode_args + scie_args
    ).assert_success()

    foo = os.path.join(str(tmpdir), "foo.py")
    with open(foo, "w") as fp:
        fp.write(
            dedent(
                """\
                from __future__ import print_function

                import colors


                bar = 42
                print(colors.green("hello"), bar)
                """
            )
        )

    assert (
        "{hello} 42".format(hello=colors.green("hello"))
        == subprocess.check_output(args=[pex, foo]).decode("utf-8").strip()
    )

    scie_base = os.path.join(str(tmpdir), "nce")

    def assert_inspect(
        args,  # type: List[str]
        **env  # type: Any
    ):
        # type: (...) -> None
        with open(os.path.join(str(tmpdir), "pexpect.log"), "wb") as log, closing(
            pexpect.spawn(
                pex,
                args,
                # MyPy expects an os._Environ[str] private type from the typeshed not compatible
                # with Dict[str, str] but this code does actually work at runtime!
                env=make_env(SCIE_BASE=scie_base, **env),  # type: ignore[arg-type]
                dimensions=(24, 80),
                logfile=log,
            )
        ) as process:
            process.expect_exact(
                "{green_hello} 42".format(green_hello=colors.green("hello")).encode("utf-8"),
                # The PyPy venv scies are quite slow to set up; so we extend the initial timeout
                # for those even more.
                timeout=pexpect_timeout * (6 if IS_PYPY and scie_args else 3),
            )
            process.expect_exact(b">>>", timeout=pexpect_timeout)
            process.sendline(b"print(colors.blue(bar))")
            process.expect_exact(colors.blue(42).encode("utf-8"), timeout=pexpect_timeout)
            process.expect_exact(b">>>", timeout=pexpect_timeout)
            process.sendline(b"quit()")

    assert_inspect(args=["-i", foo])
    safe_rmtree(scie_base)
    assert_inspect(args=[foo], PYTHONINSPECT=1)
