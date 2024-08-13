# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import shutil
import subprocess
import tempfile
from textwrap import dedent

import colors  # vendor:skip
import pytest

from pex.resolve.lockfile import json_codec
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any, Callable, List


@pytest.mark.parametrize(
    ["archive_pex_requirement"],
    [
        pytest.param(
            "https://github.com/VaasuDevanS/cowsay-python/archive/v5.0.zip#egg=cowsay",
            id="Create Pex [Pip Proprietary]",
        ),
        pytest.param(
            "cowsay @ https://github.com/VaasuDevanS/cowsay-python/archive/v5.0.zip",
            id="Create Pex [PEP-508]",
        ),
    ],
)
def test_pex_archive_direct_reference(
    tmpdir,  # type: Any
    archive_pex_requirement,  # type: str
):
    # type: (...) -> None

    result = run_pex_command(
        args=[
            archive_pex_requirement,
            "-c",
            "cowsay",
            "--",
            "Moo!",
        ]
    )
    result.assert_success()
    assert "Moo!" in result.output


@pytest.mark.parametrize(
    ["archive_lock_requirement"],
    [
        pytest.param(
            "https://github.com/VaasuDevanS/cowsay-python/archive/v5.0.zip#egg=cowsay",
            id="Create Lock [Pip Proprietary]",
        ),
        pytest.param(
            "cowsay @ https://github.com/VaasuDevanS/cowsay-python/archive/v5.0.zip",
            id="Create Lock [PEP-508]",
        ),
    ],
)
@pytest.mark.parametrize(
    ["archive_pex_requirements"],
    [
        pytest.param(
            ["https://github.com/VaasuDevanS/cowsay-python/archive/v5.0.zip#egg=cowsay"],
            id="Subset [Pip Proprietary]",
        ),
        pytest.param(
            ["cowsay @ https://github.com/VaasuDevanS/cowsay-python/archive/v5.0.zip"],
            id="Subset [PEP-508]",
        ),
        pytest.param([], id="Full"),
    ],
)
def test_lock_create_archive_direct_reference(
    tmpdir,  # type: Any
    archive_lock_requirement,  # type: str
    archive_pex_requirements,  # type: List[str]
):
    # type: (...) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")
    lock = os.path.join(str(tmpdir), "lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        archive_lock_requirement,
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()

    def assert_create_and_run_pex_from_lock():
        # type: () -> None
        result = run_pex_command(
            args=archive_pex_requirements
            + [
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--lock",
                lock,
                "-c",
                "cowsay",
                "--",
                "Moo!",
            ]
        )
        result.assert_success()
        assert "Moo!" in result.output

    assert_create_and_run_pex_from_lock()
    shutil.rmtree(pex_root)
    assert_create_and_run_pex_from_lock()


@pytest.mark.parametrize(
    ["create_local_project_lock_requirement"],
    [
        pytest.param(lambda clone_dir: clone_dir, id="Create Lock [Pip Proprietary]"),
        pytest.param(
            lambda clone_dir: "ansicolors @ file://{}".format(clone_dir), id="Create Lock [PEP-508]"
        ),
    ],
)
@pytest.mark.parametrize(
    ["create_local_project_pex_requirements"],
    [
        pytest.param(lambda clone_dir: [clone_dir], id="Subset [Pip Proprietary]"),
        pytest.param(
            lambda clone_dir: ["ansicolors @ file://{}".format(clone_dir)], id="Subset [PEP-508]"
        ),
        pytest.param(lambda clone_dir: [], id="Full"),
    ],
)
def test_lock_create_local_project_direct_reference(
    tmpdir,  # type: Any
    create_local_project_lock_requirement,  # type: Callable[[str], str]
    create_local_project_pex_requirements,  # type: Callable[[str], List[str]]
):
    # type: (...) -> None

    clone_dir = os.path.join(str(tmpdir), "ansicolors")
    subprocess.check_call(args=["git", "init", clone_dir])

    ansicolors_1_1_8_sha = "c965f5b9103c5bd32a1572adb8024ebe83278fb0"
    subprocess.check_call(
        args=[
            "git",
            "fetch",
            "--depth",
            "1",
            "https://github.com/jonathaneunice/colors",
            ansicolors_1_1_8_sha,
        ],
        cwd=clone_dir,
    )
    subprocess.check_call(args=["git", "reset", "--hard", ansicolors_1_1_8_sha], cwd=clone_dir)

    lock_requirement = create_local_project_lock_requirement(clone_dir)
    pex_requirements = create_local_project_pex_requirements(clone_dir)

    pex_root = os.path.join(str(tmpdir), "pex_root")
    lock = os.path.join(str(tmpdir), "lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        lock_requirement,
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()

    def assert_create_and_run_pex_from_lock():
        # type: () -> None
        result = run_pex_command(
            args=pex_requirements
            + [
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--lock",
                lock,
                "--",
                "-c",
                "import colors; print(colors.yellow('Vogon Constructor Fleet!'))",
            ]
        )
        result.assert_success()
        assert colors.yellow("Vogon Constructor Fleet!") == result.output.strip()

    assert_create_and_run_pex_from_lock()
    shutil.rmtree(pex_root)
    assert_create_and_run_pex_from_lock()

    with tempfile.NamedTemporaryFile() as fp:
        fp.write(
            dedent(
                """\
                diff --git a/setup.py b/setup.py
                index 0b58889..bdb7c90 100755
                --- a/setup.py
                +++ b/setup.py
                @@ -42,3 +42,4 @@ setup(
                         'Topic :: Software Development :: Libraries :: Python Modules'
                     ]
                 )
                +# Changed
                """
            ).encode("utf-8")
        )
        fp.flush()
        subprocess.check_call(args=["git", "apply", fp.name], cwd=clone_dir)

    # We patched the source but have a cached wheel built from it before the patch in
    # <PEX_ROOT>/installed_wheels; so no "download" is performed.
    assert_create_and_run_pex_from_lock()

    # But now we do need to "download" the project, build a wheel and install it. The hash check
    # should fail.
    shutil.rmtree(pex_root)
    result = run_pex_command(
        args=["--pex-root", pex_root, "--runtime-pex-root", pex_root, "--lock", lock]
    )
    result.assert_failure()

    lockfile = json_codec.load(lockfile_path=lock)
    assert 1 == len(lockfile.locked_resolves)
    locked_resolve = lockfile.locked_resolves[0]
    assert 1 == len(locked_resolve.locked_requirements)
    locked_requirement = locked_resolve.locked_requirements[0]
    assert (
        dedent(
            """\
            There was 1 error downloading required artifacts:
            1. ansicolors 1.1.8 from file://{clone_dir}
                Expected sha256 hash of {expected} when downloading ansicolors but hashed to
            """
        )
        .format(
            clone_dir=clone_dir,
            expected=locked_requirement.artifact.fingerprint.hash,
        )
        .strip()
        in result.error
    ), result.error
