# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys
from typing import Text, Tuple

import pytest

from pex.testing import ALL_PY_VERSIONS, ensure_python_interpreter, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, List


@pytest.mark.parametrize(
    ["execution_mode_args"],
    [
        pytest.param([], id="zipapp"),
        pytest.param(["--venv"], id="venv"),
    ],
)
def test_execute(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    cowsay = os.path.join(str(tmpdir), "cowsay.pex")
    run_pex_command(
        args=["cowsay==4.0", "-c", "cowsay", "-o", cowsay, "--sh-boot"] + execution_mode_args
    ).assert_success()
    assert "4.0" == subprocess.check_output(args=[cowsay, "--version"]).decode("utf-8").strip()


def interpreters():
    # type: () -> Iterable[Tuple[Text, List[Text]]]

    def iter_interpreters():
        # type: () -> Iterator[Tuple[Text, List[Text]]]

        def entry(path):
            # type: (Text) -> Tuple[Text, List[Text]]
            return os.path.basename(path), [path]

        yield entry(sys.executable)

        for version in ALL_PY_VERSIONS:
            interpreter = ensure_python_interpreter(version)
            yield entry(interpreter)

        locations = (
            subprocess.check_output(
                args=["/usr/bin/env", "bash", "-c", "command -v ash bash busybox dash ksh sh zsh"]
            )
            .decode("utf-8")
            .splitlines()
        )
        for location in locations:
            basename = os.path.basename(location)
            if "busybox" == basename:
                yield "ash (via busybox)", [location, "ash"]
            else:
                yield entry(location)

    return sorted({name: args for name, args in iter_interpreters()}.items())


@pytest.mark.parametrize(
    ["interpreter_cmd"],
    [pytest.param(args, id=name) for name, args in interpreters()],
)
def test_execute_via_interpreter(
    tmpdir,  # type: Any
    interpreter_cmd,  # type: List[str]
):
    # type: (...) -> None

    cowsay = os.path.join(str(tmpdir), "cowsay.pex")
    run_pex_command(
        args=["cowsay==4.0", "-c", "cowsay", "-o", cowsay, "--sh-boot"]
    ).assert_success()

    assert (
        "4.0"
        == subprocess.check_output(args=interpreter_cmd + [cowsay, "--version"])
        .decode("utf-8")
        .strip()
    )


def test_python_shebang_respected(tmpdir):
    # type: (Any) -> None

    cowsay = os.path.join(str(tmpdir), "cowsay.pex")
    run_pex_command(
        args=[
            "cowsay==4.0",
            "-c",
            "cowsay",
            "-o",
            cowsay,
            "--sh-boot",
            "--python-shebang",
            # This is a strange shebang ~no-one would use since it short-circuits the PEX execution
            # to always just print the Python interpreter version, but it serves the purposes of:
            # 1. Proving our python shebang is honored by the bash boot.
            # 2. The bash boot treatment can handle shebangs with arguments in them.
            "{python} -V".format(python=sys.executable),
        ]
    ).assert_success()

    # N.B.: Python 2.7 does not send version to stdout; so we redirect stdout to stderr to be able
    # to uniformly retrieve the Python version.
    output = subprocess.check_output(args=[cowsay], stderr=subprocess.STDOUT).decode("utf-8")
    version = "Python {version}".format(version=".".join(map(str, sys.version_info[:3])))
    assert output.startswith(version), output
