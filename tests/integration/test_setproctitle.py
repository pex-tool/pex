# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path
import subprocess
import sys
import sysconfig
from textwrap import dedent

import pytest

from pex import variables
from pex.common import safe_open
from pex.compatibility import commonpath
from pex.interpreter import PythonInterpreter
from pex.layout import Layout
from pex.pep_427 import InstallableType
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from testing import IS_MAC, run_pex_command
from testing.pep_427 import get_installable_type_flag

if TYPE_CHECKING:
    from typing import Any, Text, Tuple


@pytest.mark.parametrize("venv", [pytest.param(True, id="VENV"), pytest.param(False, id="UNZIP")])
@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
@pytest.mark.parametrize(
    "installable_type",
    [
        pytest.param(installable_type, id=installable_type.value)
        for installable_type in InstallableType.values()
    ],
)
def test_setproctitle(
    tmpdir,  # type: Any
    venv,  # type: bool
    layout,  # type: Layout.Value
    installable_type,  # type: InstallableType.Value
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

    build_pex_args = [
        "-D",
        src,
        "-m",
        "app",
        "--layout",
        layout.value,
        get_installable_type_flag(installable_type),
    ]
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
        expected = PythonInterpreter.get().resolve_base_interpreter()
        actual = PythonInterpreter.from_binary(str(exe)).resolve_base_interpreter()
        python_framework = sysconfig.get_config_var("PYTHONFRAMEWORKINSTALLDIR")
        if IS_MAC and expected != actual and python_framework:
            # Mac framework Python distributions have two Python binaries (starred) as well as
            # several symlinks. The layout looks like so:
            #   /Library/Frameworks/
            #       Python.framework/  # sysconfig.get_config_var("PYTHONFRAMEWORKINSTALLDIR")
            #           Versions/X.Y/  # sys.prefix
            #               bin/
            #                   python -> pythonX.Y
            #                   pythonX -> pythonX.Y
            #                   *pythonX.Y
            #           Resources/Python.app/
            #               Contents/MacOS/
            #                   *Python
            #
            # In some versions of Python, the bin Python, when executed, gets a sys.executable of
            # the corresponding Python resource. On others, they each retain a sys.executable
            # faithful to their launcher file path. It's the latter type we're working around here.
            assert python_framework == commonpath(
                (python_framework, expected.binary, actual.binary)
            )
            assert expected.prefix == actual.prefix
            assert expected.version == actual.version
        else:
            assert expected == actual

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
        # <PEX_ROOT>/venvs/<venv long dir>/bin/python -sE <PEX_ROOT>/venvs/<venv long dir>/pex
        # <args...>
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
        # <python> <PEX_ROOT>/unzipped_pexes/<unzipped pex dir> <args...>
        installed_location, rest = args.split(" ", 1)
        assert variables.unzip_dir(pex_info.pex_root, pex_info.pex_hash) == installed_location
        assert "--some arguments here" == rest

    setproctitle_pex_file = os.path.join(str(tmpdir), "pex.file.titled")
    exe, args = grab_ps(setproctitle_pex_file, "setproctitle")
    assert_expected_python(exe)
    assert "{pex_file} --some arguments here".format(pex_file=setproctitle_pex_file) == args
