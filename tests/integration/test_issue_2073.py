# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import re
import subprocess

from pex.resolve import abbreviated_platforms
from pex.targets import AbbreviatedPlatform
from pex.typing import TYPE_CHECKING
from testing import IS_LINUX, IntegResults, run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


FOREIGN_PLATFORM_311 = (
    "macosx_10.9_x86_64-cp-311-cp311" if IS_LINUX else "linux_x86_64-cp-311-cp311"
)
ABBREVIATED_FOREIGN_PLATFORM_311 = AbbreviatedPlatform.create(
    abbreviated_platforms.create(FOREIGN_PLATFORM_311)
)


def assert_psutil_cross_build_failure(result):
    # type: (IntegResults) -> None
    result.assert_failure()
    assert (
        re.search(
            r"No pre-built wheel was available for psutil 5\.9\.1\.{eol}"
            r"Successfully built the wheel psutil-5\.9\.1-\S+\.whl from the sdist "
            r"psutil-5\.9\.1\.tar\.gz but it is not compatible with the requested foreign target "
            r"{foreign_target}\.{eol}"
            r"You'll need to build a wheel from psutil-5\.9\.1\.tar\.gz on the foreign target platform "
            r"and make it available to Pex via a `--find-links` repo or a custom `--index`\.".format(
                eol=os.linesep,
                foreign_target=ABBREVIATED_FOREIGN_PLATFORM_311.render_description(),
            ),
            result.error,
        )
        is not None
    ), result.error


def assert_cowsay_cross_build_success(
    tmpdir,  # type: Any
    *args  # type: str
):
    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=["cowsay==5.0", "-c", "cowsay", "--platform", FOREIGN_PLATFORM_311, "-o", pex]
        + list(args)
    ).assert_success()
    assert "5.0" == subprocess.check_output(args=[pex, "--version"]).decode("utf-8").strip()


def test_standard_resolve_foreign_platform_yolo_cross_build(tmpdir):
    # type: (Any) -> None

    # There is no pre-built wheel for CPython 3.11 on any platform; so we expect failure from the
    # "cross-build" attempt.
    assert_psutil_cross_build_failure(
        run_pex_command(args=["psutil==5.9.1", "--platform", FOREIGN_PLATFORM_311])
    )

    # The cowsay 5.0 distribution is sdist-only. We should grab this and attempt a build to see if
    # we succeed and if the resulting wheel is compatible, which it should be since cowsay 5.0 is
    # known to build to a py2.py3 universal wheel.
    assert_cowsay_cross_build_success(tmpdir)


def create_lock(
    lock,  # type: str
    *args  # type: str
):
    # type: (...) -> IntegResults
    return run_pex3(
        "lock",
        "create",
        "--style",
        "universal",
        "--target-system",
        "linux",
        "--target-system",
        "mac",
        "-o",
        lock,
        "--indent",
        "2",
        *args
    )


def test_lock_create_foreign_platform_yolo_cross_build(tmpdir):
    # type: (Any) -> None

    lock = os.path.join(str(tmpdir), "lock")

    assert_psutil_cross_build_failure(
        create_lock(lock, "--platform", FOREIGN_PLATFORM_311, "psutil==5.9.1")
    )

    create_lock(lock, "--platform", FOREIGN_PLATFORM_311, "cowsay==5.0").assert_success()


def test_lock_resolve_foreign_platform_yolo_cross_build(tmpdir):
    # type: (Any) -> None

    lock = os.path.join(str(tmpdir), "lock")
    create_lock(lock, "psutil==5.9.1", "cowsay==5.0").assert_success()

    assert_psutil_cross_build_failure(
        run_pex_command(args=["psutil==5.9.1", "--platform", FOREIGN_PLATFORM_311, "--lock", lock])
    )

    assert_cowsay_cross_build_success(tmpdir, "--lock", lock)
