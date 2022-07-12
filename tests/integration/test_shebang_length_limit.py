# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import errno
import json
import os
import subprocess
from typing import Any, Callable, List

import pytest

from pex.common import chmod_plus_x, touch
from pex.testing import IS_PYPY, run_pex_command


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


EXECUTION_MODE_ARGS_PERMUTATIONS = [
    pytest.param([], id="ZIPAPP"),
    pytest.param(["--venv"], id="VENV"),
    pytest.param(["--sh-boot"], id="ZIPAPP (--sh-boot)"),
    pytest.param(["--venv", "--sh-boot"], id="VENV (--sh-boot)"),
]


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
