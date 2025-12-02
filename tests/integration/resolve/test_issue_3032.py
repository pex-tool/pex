# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import sys

from pex.dist_metadata import Requirement
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Optional

    import colors  # vendor:skip
else:
    from pex.third_party import colors


def create_lock(
    tmpdir,  # type: Tempdir
    requirement,  # type: str
):
    # type: (...) -> str
    lock = tmpdir.join("lock.json")
    run_pex3("lock", "create", "-o", lock, "--indent", "2", requirement).assert_success()
    return lock


def create_pylock(
    tmpdir,  # type: Tempdir
    lock,  # type: str
):
    # type: (...) -> str
    pylock = tmpdir.join("pylock.toml")
    run_pex3("lock", "export", "--format", "pep-751", lock, "-o", pylock).assert_success()
    return pylock


def assert_subset_succeeds(
    tmpdir,  # type: Tempdir
    lock,  # type: str
    requirement,  # type: str
    test_pylock=True,  # type: bool
):
    # type: (...) -> None

    result = run_pex_command(
        args=[
            "--lock",
            lock,
            requirement,
            "--",
            "-c",
            "import colors; print(colors.green('subset'))",
        ]
    )
    result.assert_success()
    assert colors.green("subset") == result.output.strip()

    if not test_pylock:
        return
    pylock = create_pylock(tmpdir, lock)
    result = run_pex_command(
        args=[
            "--pylock",
            pylock,
            requirement,
            "--",
            "-c",
            "import colors; print(colors.yellow('subset'))",
        ]
    )
    result.assert_success()
    assert colors.yellow("subset") == result.output.strip()


def assert_subset_fails(
    tmpdir,  # type: Tempdir
    lock,  # type: str
    requirement,  # type: str
    expect_existing=None,  # type: Optional[str]
    test_pylock=True,  # type: bool
):
    # type: (...) -> None

    def expected_error_message(lock_path):
        # type: (str) -> str
        expected = [
            "Found 1 URL requirement not present in the lock at {lock}:".format(lock=lock_path),
            "1. {requirement}".format(requirement=requirement),
        ]
        if expect_existing:
            expected.append(
                "   locked version is: {existing}".format(
                    existing=Requirement.parse(expect_existing)
                )
            )
        return "\n".join(expected)

    result = run_pex_command(args=["--lock", lock, requirement])
    result.assert_failure()
    assert expected_error_message(lock) in result.error, result.error

    if not test_pylock:
        return
    pylock = create_pylock(tmpdir, lock)
    result = run_pex_command(args=["--pylock", pylock, requirement])
    result.assert_failure()
    assert expected_error_message(pylock) in result.error, result.error


def test_direct_reference_subset(tmpdir):
    # type: (Tempdir) -> None

    lock = create_lock(
        tmpdir,
        (
            "ansicolors @ https://files.pythonhosted.org/packages/53/18/"
            "a56e2fe47b259bb52201093a3a9d4a32014f9d85071ad07e9d60600890ca/"
            "ansicolors-1.1.8-py2.py3-none-any.whl"
        ),
    )
    assert_subset_succeeds(
        tmpdir,
        lock,
        (
            "ansicolors @ https://files.pythonhosted.org/packages/53/18/"
            "a56e2fe47b259bb52201093a3a9d4a32014f9d85071ad07e9d60600890ca/"
            "ansicolors-1.1.8-py2.py3-none-any.whl"
        ),
    )
    assert_subset_succeeds(
        tmpdir,
        lock,
        (
            "ansicolors@ https://files.pythonhosted.org/packages/53/18/"
            "a56e2fe47b259bb52201093a3a9d4a32014f9d85071ad07e9d60600890ca/"
            "ansicolors-1.1.8-py2.py3-none-any.whl"
        ),
    )
    assert_subset_fails(
        tmpdir,
        lock,
        (
            "ansicolors @ https://files.pythonhosted.org/packages/76/31/"
            "7faed52088732704523c259e24c26ce6f2f33fbeff2ff59274560c27628e/"
            "ansicolors-1.1.8.zip"
        ),
        expect_existing=(
            "ansicolors @ https://files.pythonhosted.org/packages/53/18/"
            "a56e2fe47b259bb52201093a3a9d4a32014f9d85071ad07e9d60600890ca/"
            "ansicolors-1.1.8-py2.py3-none-any.whl"
        ),
    )
    assert_subset_fails(
        tmpdir,
        lock,
        (
            "jane @ https://files.pythonhosted.org/packages/53/18/"
            "a56e2fe47b259bb52201093a3a9d4a32014f9d85071ad07e9d60600890ca/"
            "ansicolors-1.1.8-py2.py3-none-any.whl"
        ),
    )


def test_vcs_requirement_subset(tmpdir):
    # type: (Tempdir) -> None

    lock = create_lock(
        tmpdir, "ansicolors@ git+https://github.com/jonathaneunice/colors.git@358f347"
    )

    test_pylock = sys.version_info[0] != 2
    assert_subset_succeeds(
        tmpdir,
        lock,
        "ansicolors@ git+https://github.com/jonathaneunice/colors.git@358f347",
        test_pylock=test_pylock,
    )
    assert_subset_succeeds(
        tmpdir,
        lock,
        "ansicolors @ git+https://github.com/jonathaneunice/colors.git@358f347",
        test_pylock=test_pylock,
    )
    assert_subset_fails(
        tmpdir,
        lock,
        "ansicolors @ git+https://github.com/jonathaneunice/colors@358f347",
        expect_existing="ansicolors@ git+https://github.com/jonathaneunice/colors.git@358f347",
        test_pylock=test_pylock,
    )
    assert_subset_fails(
        tmpdir,
        lock,
        (
            "ansicolors @ git+https://github.com/jonathaneunice/"
            "colors.git@358f3471bed3e98c6d7dabec936968f7e1a05eb7"
        ),
        expect_existing="ansicolors@ git+https://github.com/jonathaneunice/colors.git@358f347",
        test_pylock=test_pylock,
    )
    assert_subset_fails(
        tmpdir,
        lock,
        "bob @ git+https://github.com/jonathaneunice/colors.git@358f347",
        test_pylock=test_pylock,
    )
