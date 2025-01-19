# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import re
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.layout import Layout
from pex.typing import TYPE_CHECKING
from testing import all_pythons, make_env, run_pex_command
from testing.pytest.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, List, Text, Tuple


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


@pytest.mark.parametrize(
    ["execution_mode_args"],
    [
        pytest.param([], id="zipapp"),
        pytest.param(["--venv"], id="venv"),
    ],
)
def test_issue_1881(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")
    os.mkdir(pex_root)
    # Test that the runtime_pex_root is respected even when it is unwritable at build time.
    os.chmod(pex_root, 0o555)
    cowsay = os.path.join(str(tmpdir), "cowsay.pex")
    run_pex_command(
        args=[
            "cowsay==4.0",
            "-c",
            "cowsay",
            "-o",
            cowsay,
            "--python-shebang",
            sys.executable,
            "--sh-boot",
            "--runtime-pex-root",
            pex_root,
        ]
        + execution_mode_args
    ).assert_success()
    # simulate pex_root writable at runtime.
    os.chmod(pex_root, 0o777)

    def _execute_cowsay_pex():
        return (
            subprocess.check_output(
                args=[cowsay, "--version"], env=make_env(PEX_VERBOSE=1), stderr=subprocess.STDOUT
            )
            .decode("utf-8")
            .strip()
        )

    # When this string is logged from the sh_boot script it indicates that the slow
    # path of running the zipapp via python interpreter taken.
    slow_path_output = "Running zipapp pex to lay itself out under PEX_ROOT."
    assert slow_path_output in _execute_cowsay_pex()
    assert slow_path_output not in _execute_cowsay_pex()


def interpreters():
    # type: () -> Iterable[Tuple[Text, List[Text]]]

    def iter_interpreters():
        # type: () -> Iterator[Tuple[Text, List[Text]]]

        def entry(path):
            # type: (Text) -> Tuple[Text, List[Text]]
            return os.path.basename(path), [path]

        yield entry(sys.executable)

        for interpreter in all_pythons():
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


execution_mode = pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--venv"], id="VENV"),
        pytest.param(["--sh-boot"], id="ZIPAPP (--sh-boot)"),
        pytest.param(["--venv", "--sh-boot"], id="VENV (--sh-boot)"),
    ],
)
layouts = pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)


@execution_mode
@layouts
def test_issue_1782(
    tmpdir,  # type: Tempdir
    pex_project_dir,  # type: str
    execution_mode_args,  # type: List[str]
    layout,  # type: Layout.Value
):
    # type: (...) -> None

    pex = os.path.realpath(tmpdir.join("pex.sh"))
    pex_exe = pex if layout is Layout.ZIPAPP else os.path.join(pex, "pex")

    pex_root = os.path.realpath(tmpdir.join("pex_root"))
    python = "python{major}.{minor}".format(major=sys.version_info[0], minor=sys.version_info[1])
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            pex_project_dir,
            "-c",
            "pex",
            "-o",
            pex,
            "--python-shebang",
            "/usr/bin/env {python}".format(python=python),
            "--layout",
            str(layout),
        ]
        + execution_mode_args
    ).assert_success()

    if (
        sys.version_info[:2] >= (3, 14)
        and "--venv" not in execution_mode_args
        and layout is not Layout.LOOSE
    ):
        argv0 = r"python(?:3(?:\.\d{{2,}})?)? {pex}".format(pex=re.escape(pex_exe))
    else:
        argv0 = re.escape(os.path.basename(pex_exe))
    usage_line_re = re.compile(r"^usage: {argv0}".format(argv0=argv0))
    help_line1 = (
        subprocess.check_output(
            args=[pex_exe, "-h"], env=make_env(COLUMNS=max(80, len(usage_line_re.pattern) + 10))
        )
        .decode("utf-8")
        .splitlines()[0]
        .strip()
    )
    assert usage_line_re.match(help_line1), (
        "\n"
        "expected: {expected}\n"
        "actual:   {actual}".format(expected=usage_line_re.pattern, actual=help_line1)
    )
    assert (
        pex
        == subprocess.check_output(
            args=[pex_exe, "-c", "import os; print(os.environ['PEX'])"],
            env=make_env(PEX_INTERPRETER=1),
        )
        .decode("utf-8")
        .strip()
    )


@execution_mode
@layouts
def test_argv0(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
    layout,  # type: Layout.Value
):
    # type: (...) -> None

    pex = os.path.realpath(os.path.join(str(tmpdir), "pex.sh"))
    pex_exe = pex if layout is Layout.ZIPAPP else os.path.join(pex, "pex")

    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "app.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import json
                import os
                import sys


                def main():
                    print(json.dumps({"PEX": os.environ["PEX"], "argv0": sys.argv[0]}))


                if __name__ == "__main__":
                    main()
                """
            )
        )

    run_pex_command(
        args=["-D", src, "-e", "app:main", "-o", pex, "--layout", str(layout)] + execution_mode_args
    ).assert_success()
    assert {"PEX": pex, "argv0": pex_exe} == json.loads(subprocess.check_output(args=[pex_exe]))

    run_pex_command(
        args=["-D", src, "-m", "app", "-o", pex, "--layout", str(layout)] + execution_mode_args
    ).assert_success()
    data = json.loads(subprocess.check_output(args=[pex_exe]))
    assert pex == data.pop("PEX")
    assert "app.py" == os.path.basename(data.pop("argv0")), (
        "When executing modules we expect runpy.run_module to `alter_sys` in order to support "
        "pickling and other use cases as outlined in https://github.com/pex-tool/pex/issues/1018."
    )
    assert {} == data
