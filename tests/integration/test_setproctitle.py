# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path
import subprocess
import sys
from textwrap import dedent
from typing import Text

import pytest

from pex import variables
from pex.common import safe_open
from pex.interpreter import PythonInterpreter
from pex.layout import Layout
from pex.pex_info import PexInfo
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Tuple


@pytest.mark.parametrize("venv", [pytest.param(True, id="VENV"), pytest.param(False, id="UNZIP")])
@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
def test_setproctitle(
    tmpdir,  # type: Any
    venv,  # type: bool
    layout,  # type: Layout.Value
):
    # type: (...) -> None

    pid_file = os.path.join(str(tmpdir), "pid")
    os.mkfifo(pid_file)

    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "app.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from __future__ import print_function

                import os
                import threading

                # Indicate PEX boot is complete and we've reached user code.
                with open({pid_file!r}, "w") as fp:
                    print(str(os.getpid()), file=fp)

                # Run forever to ensure there is time to read out our `ps` info.
                cv = threading.Condition()
                with cv:
                    cv.wait()
                """.format(
                    pid_file=pid_file
                )
            )
        )

    build_pex_args = ["-D", src, "-m", "app", "--layout", layout.value]
    if venv:
        build_pex_args.append("--venv")

    def grab_ps(
        pex,  # type: str
        *extra_pex_args  # type: str
    ):
        # type: (...) -> Tuple[Text, Text]
        run_pex_command(args=build_pex_args + ["-o", pex] + list(extra_pex_args)).assert_success()

        process = subprocess.Popen(args=[sys.executable, pex, "--some", "arguments", "here"])
        try:
            # N.B.: We need to block on receiving the pid via fifo to prove that the PEX runtime has
            # finished booting and completed any and all re-execs and landed in user code.
            with open(pid_file) as fp:
                assert process.pid == int(fp.read().strip())

            exe, args = (
                subprocess.check_output(
                    args=["ps", "-p", str(process.pid), "-o", "command=", "-ww"]
                )
                .decode("utf-8")
                .strip()
                .split(" ", 1)
            )
            return exe, args
        finally:
            process.kill()

    def assert_expected_python(exe):
        # type: (Text) -> None
        assert (
            PythonInterpreter.get().resolve_base_interpreter()
            == PythonInterpreter.from_binary(str(exe)).resolve_base_interpreter()
        )

    pex_file = os.path.join(str(tmpdir), "pex.file")
    exe, args = grab_ps(pex_file)
    assert_expected_python(exe)

    pex_info = PexInfo.from_pex(pex_file)
    assert pex_info.pex_hash is not None

    if Layout.LOOSE == layout and not venv:
        # N.B.: A non-venv loose PEX runs from where it is and presents a nice ps without help.
        assert "{pex_file} --some arguments here".format(pex_file=pex_file) == args
    elif venv:
        # A `--venv` mode PEX boot terminates in a final process of:
        # ~/.pex/venvs/<venv short dir>/bin/python -sE ~/.pex/venvs/<venv long dir>/pex <args...>
        python_args, installed_location, rest = args.split(" ", 2)
        assert "-sE" == python_args
        assert (
            os.path.join(
                variables.venv_dir(
                    pex_file,
                    pex_info.pex_root,
                    pex_info.pex_hash,
                    has_interpreter_constraints=False,
                ),
                "pex",
            )
            == installed_location
        )
        assert "--some arguments here" == rest
    else:
        # All other PEX boots terminate in an unzipped execution that looks like:
        # <python> ~/.pex/unzipped_pexes/<unzipped pex dir> <args...>
        installed_location, rest = args.split(" ", 1)
        assert variables.unzip_dir(pex_info.pex_root, pex_info.pex_hash) == installed_location
        assert "--some arguments here" == rest

    setproctitle_pex_file = os.path.join(str(tmpdir), "pex.file.titled")
    exe, args = grab_ps(setproctitle_pex_file, "setproctitle")
    assert_expected_python(exe)
    assert "{pex_file} --some arguments here".format(pex_file=setproctitle_pex_file) == args
