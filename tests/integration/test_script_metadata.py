# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re
import subprocess
import sys
from textwrap import dedent

import colors  # vendor:skip

from pex.targets import LocalInterpreter
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING
from testing import PY310, ensure_python_interpreter, run_pex_command

if TYPE_CHECKING:
    from typing import Any


def current_interpreter_applies(specifier):
    # type: (str) -> bool

    return LocalInterpreter.create().requires_python_applies(
        SpecifierSet(specifier), source=__name__ + ".current_interpreter_applies"
    )


def test_nominal(tmpdir):
    # type: (Any) -> None

    curl_exe = os.path.join(str(tmpdir), "curl.py")
    with open(curl_exe, "w") as fp:
        fp.write(
            dedent(
                """\
                # /// script
                # dependencies = ["requests"]
                # requires-python = ">=3.8,<3.13"
                # ///

                import io
                import os
                import sys
                from typing import NoReturn

                import requests


                def curl(url: str) -> None:
                    for chunk in requests.get(url, stream=True).iter_content(
                        chunk_size=io.DEFAULT_BUFFER_SIZE
                    ):
                        sys.stdout.buffer.write(chunk)


                def main() -> NoReturn:
                    if len(sys.argv) != 2:
                        sys.exit(f"Usage: {os.environ.get('PEX', sys.argv[0])} <URL>")
                    try:
                        curl(sys.argv[1])
                        sys.exit(0)
                    except requests.RequestException as e:
                        sys.exit(str(e))


                if __name__ == "__main__":
                    main()
                """
            )
        )
    curl_pex = os.path.join(str(tmpdir), "curl.pex")
    args = ["--exe", curl_exe, "-o", curl_pex]
    python = sys.executable
    if not current_interpreter_applies(">=3.8,<3.13"):
        python = ensure_python_interpreter(PY310)
        args.append("--python")
        args.append(python)

    run_pex_command(args=args).assert_success()
    output = (
        subprocess.check_output(args=[python, curl_pex, "https://docs.pex-tool.org"])
        .decode("utf-8")
        .strip()
    )
    assert output.startswith("<!doctype html>"), output
    assert output.endswith("</html>"), output


def test_dependencies_additive(tmpdir):
    # type: (Any) -> None

    cowsay_exe = os.path.join(str(tmpdir), "cowsay.py")
    with open(cowsay_exe, "w") as fp:
        fp.write(
            dedent(
                """\
                # /// script
                # dependencies = ["cowsay==5.0"]
                # ///

                from cowsay import main
                try:
                    from colors import yellow
                except ImportError:
                    yellow = lambda text: text

                if __name__ == "__main__":
                    main.tux(yellow("Bird Beak!"))
                """
            )
        )
    run_pex_command(args=["--exe", cowsay_exe]).assert_success(
        expected_output_re=r".*^{expected}$.*".format(expected=re.escape("| Bird Beak! |")),
        re_flags=re.DOTALL | re.MULTILINE,
    )
    run_pex_command(args=["--exe", cowsay_exe, "ansicolors==1.1.8"]).assert_success(
        expected_output_re=r".*^{expected}$.*".format(
            expected=re.escape("| {colorized} |".format(colorized=colors.yellow("Bird Beak!")))
        ),
        re_flags=re.DOTALL | re.MULTILINE,
    )


def test_dependencies_conflicting(tmpdir):
    # type: (Any) -> None

    cowsay_exe = os.path.join(str(tmpdir), "cowsay.py")
    with open(cowsay_exe, "w") as fp:
        fp.write(
            dedent(
                """\
                # /// script
                # dependencies = ["cowsay==5.0"]
                # ///
                """
            )
        )
    run_pex_command(
        args=["--exe", cowsay_exe, "cowsay>=6.0", "--resolver-version", "pip-2020-resolver"]
    ).assert_failure(
        expected_error_re=r".*{expected}.*".format(
            expected=re.escape(
                "ERROR: Cannot install cowsay==5.0 and cowsay>=6.0 because these package versions "
                "have conflicting dependencies."
            )
        ),
        re_flags=re.DOTALL,
    )


def test_targets_additive(tmpdir):
    # type: (Any) -> None

    hello_world_exe = os.path.join(str(tmpdir), "hello-world.py")
    with open(hello_world_exe, "w") as fp:
        fp.write(
            dedent(
                """\
                # /// script
                # requires-python = ">=3.10,<3.13"
                # ///

                import os
                import sys


                if __name__ == "__main__":
                    match sys.argv:
                        case [_, single_arg]:
                            print(f"Hello {single_arg}!")
                        case _:
                            sys.exit(f"Usage {os.environ.get('PEX', sys.argv[0])} <greetee>")
                """
            )
        )

    python = (
        ensure_python_interpreter(PY310)
        if not current_interpreter_applies(">=3.10,<3.13")
        else None
    )

    # In nominal mode it should work.
    run_pex_command(args=["--exe", hello_world_exe, "--", "World"], python=python).assert_success(
        expected_output_re=r"^Hello World!$"
    )

    # As should a compatible target addition.
    run_pex_command(
        args=[
            "--exe",
            hello_world_exe,
            "--platform",
            "macosx-10.9-x86_64-cp-310-cp310",
            "--",
            "Mac, I<3 you",
        ],
        python=python,
    ).assert_success(expected_output_re=r"^Hello Mac, I<3 you!$")

    # But an incompatible target addition should be detected and fail.
    run_pex_command(
        args=[
            "--exe",
            hello_world_exe,
            "--platform",
            "macosx-10.9-x86_64-cp-39-cp39",
            "--",
            "World",
        ],
        python=python,
        quiet=True,
    ).assert_failure(
        expected_error_re=re.escape(
            "The script metadata from {script} specifies a requires-python of <3.13,>=3.10 but "
            "the following configured targets are incompatible with that constraint: abbreviated "
            "platform cp39-cp39-macosx_10_9_x86_64".format(script=hello_world_exe)
        )
    )


def test_no_script_metadata(tmpdir):
    # type: (Any) -> None

    exe = os.path.join(str(tmpdir), "exe.py")
    with open(exe, "w") as fp:
        fp.write(
            dedent(
                """\
                # /// script
                # dependencies = ["ansicolors==1.1.8"]
                # ///

                try:
                    from colors import yellow
                except ImportError:
                    yellow = lambda text: text

                if __name__ == "__main__":
                    print(yellow("Mellow"))
                """
            )
        )
    run_pex_command(args=["--exe", exe]).assert_success(
        expected_output_re=re.escape(colors.yellow("Mellow"))
    )
    run_pex_command(args=["--exe", exe, "--no-pep723"]).assert_success(expected_output_re=r"Mellow")
