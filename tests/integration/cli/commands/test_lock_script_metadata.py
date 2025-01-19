# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import re
from textwrap import dedent

import pytest

from pex.interpreter import PythonInterpreter
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.cli import run_pex3
from testing.pytest.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Union

    import colors  # vendor:skip
    from typing_extensions import Literal
else:
    from pex.third_party import colors


@pytest.fixture
def script(tmpdir):
    # type: (Tempdir) -> str

    script = tmpdir.join("script.py")
    with open(script, "w") as fp:
        fp.write(
            dedent(
                """\
                # /// script
                # dependencies = ["cowsay==5.0"]
                # ///

                import cowsay


                print(cowsay.get_output_string("cow", "Moo!"))
                """
            )
        )
    return script


def assert_lock_script_simple(
    lock,  # type: str
    script,  # type: str
    expected_message="| Moo! |",  # type: str
):
    # type: (...) -> None

    run_pex_command(args=["--lock", lock, "--exe", script]).assert_success(
        expected_output_re=r".*{message}.*".format(message=re.escape(expected_message)),
        re_flags=re.DOTALL,
    )


def test_lock_create_script_simple(
    tmpdir,  # type: Tempdir
    script,  # type: str
):
    # type: (...) -> None

    lock = tmpdir.join("lock.json")
    run_pex3("lock", "create", "--script", script, "-o", lock).assert_success()
    assert_lock_script_simple(lock, script)


def test_lock_sync_script_simple(
    tmpdir,  # type: Tempdir
    script,  # type: str
    current_interpreter,  # type: PythonInterpreter
):
    # type: (...) -> None

    lock = tmpdir.join("lock.json")
    run_pex3("lock", "sync", "--script", script, "--lock", lock).assert_success()
    assert_lock_script_simple(lock, script)

    with open(script, "w") as fp:
        fp.write(
            dedent(
                """\
                # /// script
                # dependencies = ["ansicolors==1.1.8", "cowsay==5.0"]
                # ///

                import colors
                import cowsay


                print(cowsay.get_output_string("cow", colors.green("Moo!")))
                """
            )
        )
    run_pex3("lock", "sync", "--script", script, "--lock", lock).assert_success(
        expected_error_re=re.escape(
            dedent(
                """\
                Updates for lock generated by {platform}:
                  Added ansicolors 1.1.8
                Updates to lock input requirements:
                  Added 'ansicolors==1.1.8'
                """
            ).format(platform=current_interpreter.platform.tag)
        ),
    )
    assert_lock_script_simple(
        lock, script, expected_message="| {message} |".format(message=colors.green("Moo!"))
    )


@pytest.fixture
def script2(tmpdir):
    # type: (Tempdir) -> str

    script2 = tmpdir.join("script2.py")
    with open(script2, "w") as fp:
        fp.write(
            dedent(
                """\
                # /// script
                # dependencies = ["ansicolors==1.1.8"]
                # ///

                import colors


                print(colors.green("Moo!"))
                """
            )
        )
    return script2


def assert_lock_script_multiple(
    lock,  # type: str
    script,  # type: str
    script2,  # type: str
):
    # type: (...) -> None
    run_pex_command(args=["--lock", lock, "--exe", script]).assert_success(
        expected_output_re=r".*{message}.*".format(message=re.escape("| Moo! |")),
        re_flags=re.DOTALL,
    )
    run_pex_command(args=["--lock", lock, "--exe", script2]).assert_success(
        expected_output_re=re.escape(
            "{message}{eol}".format(message=colors.green("Moo!"), eol=os.linesep)
        )
    )


def test_lock_create_script_multiple(
    tmpdir,  # type: Tempdir
    script,  # type: str
    script2,  # type: str
):
    # type: (...) -> None

    lock = tmpdir.join("lock.json")
    run_pex3("lock", "create", "--script", script, "--script", script2, "-o", lock).assert_success()
    assert_lock_script_multiple(lock, script, script2)


def test_lock_sync_script_multiple(
    tmpdir,  # type: Tempdir
    script,  # type: str
    script2,  # type: str
):
    # type: (...) -> None

    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock", "sync", "--script", script, "--script", script2, "--lock", lock
    ).assert_success()
    assert_lock_script_multiple(lock, script, script2)


@pytest.fixture
def script3(tmpdir):
    # type: (Tempdir) -> str

    script3 = tmpdir.join("script3.py")
    with open(script3, "w") as fp:
        fp.write(
            dedent(
                """\
                # /// script
                # requires-python = "==3.13.*"
                # ///
                """
            )
        )
    return script3


def assert_lock_script_conflict(
    verb,  # type: Union[Literal["create"], Literal["sync"]]
    script,  # type: str
    *extra_args  # type: str
):
    # type: (...) -> None

    run_pex3(
        "lock", verb, "--platform", "linux-aarch64-cp-39-cp39", "--script", script, *extra_args
    ).assert_failure(
        expected_error_re=re.escape(
            dedent(
                """\
                PEP-723 scripts were specified that are incompatible with 1 lock target:
                1. abbreviated platform cp39-cp39-linux_aarch64 is not compatible with 1 script:
                   + {script} requires Python '==3.13.*'
                """
            ).format(script=script)
        ),
        re_flags=re.DOTALL | re.MULTILINE,
    )


def test_lock_script_conflict(
    tmpdir,  # type: Tempdir
    script3,  # type: str
):
    # type: (...) -> None

    lock = tmpdir.join("lock.json")
    assert_lock_script_conflict("create", script3, "-o", lock)
    assert_lock_script_conflict("sync", script3, "--lock", lock)