# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import errno
import json
import os
import subprocess
import sys
from textwrap import dedent
from typing import Callable, Text, Tuple

import pytest

from pex.common import chmod_plus_x, safe_open, touch
from pex.testing import (
    ALL_PY_VERSIONS,
    IS_PYPY,
    ensure_python_interpreter,
    make_env,
    run_pex_command,
)
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


EXECUTION_MODE_ARGS_PERMUTATIONS = [
    pytest.param([], id="ZIPAPP"),
    pytest.param(["--venv"], id="VENV"),
    pytest.param(["--sh-boot"], id="ZIPAPP (--sh-boot)"),
    pytest.param(["--venv", "--sh-boot"], id="VENV (--sh-boot)"),
]


@pytest.mark.parametrize("execution_mode_args", EXECUTION_MODE_ARGS_PERMUTATIONS)
def test_issue_1782(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex = os.path.realpath(os.path.join(str(tmpdir), "pex.sh"))
    run_pex_command(
        args=[pex_project_dir, "-c", "pex", "-o", pex] + execution_mode_args
    ).assert_success()

    help_line1 = subprocess.check_output(args=[pex, "-h"]).decode("utf-8").splitlines()[0]
    assert help_line1.startswith("usage: {pex} ".format(pex=os.path.basename(pex))), help_line1
    assert (
        pex
        == subprocess.check_output(
            args=[pex, "-c", "import os; print(os.environ['PEX'])"], env=make_env(PEX_INTERPRETER=1)
        )
        .decode("utf-8")
        .strip()
    )


@pytest.mark.parametrize("execution_mode_args", EXECUTION_MODE_ARGS_PERMUTATIONS)
def test_argv0(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex = os.path.realpath(os.path.join(str(tmpdir), "pex.sh"))
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
        args=["-D", src, "-e", "app:main", "-o", pex] + execution_mode_args
    ).assert_success()
    assert {"PEX": pex, "argv0": pex} == json.loads(subprocess.check_output(args=[pex]))

    run_pex_command(args=["-D", src, "-m", "app", "-o", pex] + execution_mode_args).assert_success()
    data = json.loads(subprocess.check_output(args=[pex]))
    assert pex == data.pop("PEX")
    assert "app.py" == os.path.basename(data.pop("argv0")), (
        "When executing modules we expect runpy.run_module to `alter_sys` in order to support "
        "pickling and other use cases as outlined in https://github.com/pantsbuild/pex/issues/1018."
    )
    assert {} == data


def find_max_length(
    seed_max,  # type: int
    is_too_long,  # type: Callable[[int], bool]
):
    # type: (...) -> int

    too_long_low_watermark = seed_max
    ok_high_watermark = 0
    current_length = seed_max
    steps = 0
    while True:
        steps += 1
        if is_too_long(current_length):
            too_long_low_watermark = min(too_long_low_watermark, current_length)
        elif current_length + 1 == too_long_low_watermark:
            return current_length
        else:
            assert current_length < seed_max, "Did not probe high enough for shebang length limit."
            ok_high_watermark = max(ok_high_watermark, current_length)
        assert ok_high_watermark < too_long_low_watermark
        current_length = ok_high_watermark + (too_long_low_watermark - ok_high_watermark) // 2


# Pytest fails to cleanup tmp dirs used probing file_path_length_limit and this squashes a very
# large ream of warnings.
pytestmark = pytest.mark.filterwarnings("ignore:\\(rm_rf\\) error removing.*:pytest.PytestWarning")


@pytest.fixture(scope="module")
def file_path_length_limit(tmpdir_factory):
    # type: (Any) -> int

    def file_path_too_long(length):
        # type: (int) -> bool
        path = str(tmpdir_factory.mktemp("td"))
        while len(path) < length - len(os.path.join("directory", "x")):
            path = os.path.join(path, "directory")
            try:
                os.mkdir(path)
            except OSError as e:
                if e.errno == errno.ENAMETOOLONG:
                    return True
                elif e.errno != errno.EEXIST:
                    raise e

        if len(path) < length:
            padding = length - len(path) - len(os.sep)
            path = os.path.join(path, "x" * padding)
            try:
                touch(path)
            except (IOError, OSError) as e:
                if e.errno == errno.ENAMETOOLONG:
                    return True
                raise e

        return False

    return find_max_length(seed_max=2 ** 16, is_too_long=file_path_too_long)


@pytest.fixture(scope="module")
def shebang_length_limit(
    tmpdir_factory,  # type: Any
    file_path_length_limit,  # type: int
):
    # type: (...) -> int

    def shebang_too_long(length):
        # type: (int) -> bool
        path = str(tmpdir_factory.mktemp("td"))
        while len(path) < length - len("#!\n" + os.path.join("directory", "x")):
            path = os.path.join(path, "directory")
            try:
                os.mkdir(path)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise e

        sh_path = os.path.join(path, "x" * (length - len("#!\n" + path + os.sep)))
        try:
            os.unlink(sh_path)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise e
        os.symlink("/bin/sh", sh_path)

        script = os.path.join(path, "script.sh")
        with open(script, "w") as fp:
            fp.write("#!{sh_path}\n".format(sh_path=sh_path))
            fp.write("exit 0\n")
        chmod_plus_x(script)
        try:
            return 0 != subprocess.call(args=[script])
        except OSError as e:
            if e.errno == errno.ENOEXEC:
                return True
            raise e

    return find_max_length(
        seed_max=file_path_length_limit - len(os.sep + "script.sh"), is_too_long=shebang_too_long
    )


@pytest.mark.parametrize("execution_mode_args", EXECUTION_MODE_ARGS_PERMUTATIONS)
def test_shebang_length_limit(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
    file_path_length_limit,  # type: int
    shebang_length_limit,  # type: int
):
    # type: (...) -> None

    # The short venv python used in --venv shebangs is of the form:
    #   <PEX_ROOT>/venvs/s/592c68dc/venv/bin/python
    # With no collisions, the hash dir is 8 characters, and we expect no collisions in this bespoke
    # new empty temporary dir PEX_ROOT>
    padding_dirs_length = shebang_length_limit - len(
        "#!"
        + os.path.join(
            str(tmpdir),
            "pex_root",
            "venvs",
            "s",
            "12345678",
            "venv",
            "bin",
            "pypy" if IS_PYPY else "python",
        )
        + "\n"
    )
    if padding_dirs_length > file_path_length_limit:
        pytest.skip(
            "Cannot create a PEX_ROOT in the tmp dir that both generates a too-long venv pex "
            "script shebang and yet does not generate a path to that venv pex script that is too "
            "long.\n"
            "Max shebang length: {shebang_length_limit}\n"
            "Max file path length: {file_path_length_limit}\n"
            "Temp dir length: {tmpdir_path_length}\n"
            "Temp dir:\n{tmpdir}".format(
                shebang_length_limit=shebang_length_limit,
                file_path_length_limit=file_path_length_limit,
                tmpdir_path_length=len(str(tmpdir)),
                tmpdir=tmpdir,
            )
        )

    padding_dirs_path = "directory"
    while len(padding_dirs_path) < padding_dirs_length - len(os.path.join("directory", "x")):
        padding_dirs_path = os.path.join(padding_dirs_path, "directory")
    padding_dirs_path = os.path.join(
        padding_dirs_path, "x" * (padding_dirs_length - len(padding_dirs_path + os.sep))
    )

    pex_root = os.path.realpath(os.path.join(str(tmpdir), padding_dirs_path, "pex_root"))
    pex = os.path.realpath(os.path.join(str(tmpdir), "pex.sh"))
    result = run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "-o",
            pex,
            "--seed",
            "verbose",
        ]
        + execution_mode_args
    )
    result.assert_success()
    seeded_pex = json.loads(result.output)["pex"]

    test_pex_args = ["-c", "import __main__; print(__main__.__file__)"]

    def assert_pex_works(pex_file):
        assert (
            subprocess.check_output(args=[pex_file] + test_pex_args)
            .decode("utf8")
            .startswith(pex_root)
        )

    if "--venv" in execution_mode_args:
        # Running the venv pex directly should fail since the shebang length is too long.
        with pytest.raises(OSError) as exc_info:
            subprocess.check_call(args=[seeded_pex] + test_pex_args)
        assert exc_info.value.errno == errno.ENOEXEC
    else:
        assert_pex_works(seeded_pex)

    assert_pex_works(pex)
