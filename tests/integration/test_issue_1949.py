# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path

import pytest

from pex.compatibility import commonpath
from pex.typing import TYPE_CHECKING
from testing import IntegResults, built_wheel, run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any, Iterator


@pytest.fixture
def wheel():
    # type: () -> Iterator[str]
    with built_wheel(name="not_boto", version="2.49.0a1") as whl:
        yield whl


def test_resolve_arbitrary_equality(
    tmpdir,  # type: Any
    wheel,  # type: str
):
    # type: (...) -> None

    lock = os.path.join(str(tmpdir), "lock.json")
    run_pex3(
        "lock",
        "create",
        "--no-pypi",
        "--find-links",
        os.path.dirname(wheel),
        "not_boto===2.49.0a1",
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()

    pex_root = os.path.join(str(tmpdir), "pex_root")

    def create_pex_from_lock(*additional_args):
        # type: (*str) -> IntegResults
        return run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--lock",
                lock,
            ]
            + list(additional_args)
            + ["--", "-c", "import not_boto; print(not_boto.__file__)"]
        )

    result = create_pex_from_lock()
    result.assert_success()
    assert pex_root == commonpath((pex_root, result.output.strip()))

    result = create_pex_from_lock("not_boto===2.49.0a1")
    result.assert_success()
    assert pex_root == commonpath((pex_root, result.output.strip()))

    result = create_pex_from_lock("not_boto===2.49a1")
    result.assert_failure()

    pex_repository = os.path.join(str(tmpdir), "pex_repository")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--lock",
            lock,
            "-o",
            pex_repository,
        ]
    ).assert_success()

    def create_pex_from_pex_repository(requirement):
        # type: (str) -> IntegResults
        return run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--pex-repository",
                pex_repository,
                requirement,
                "--",
                "-c",
                "import not_boto; print(not_boto.__file__)",
            ]
        )

    result = create_pex_from_pex_repository("not_boto===2.49.0a1")
    result.assert_success()
    assert pex_root == commonpath((pex_root, result.output.strip()))

    result = create_pex_from_pex_repository("not_boto===2.49a1")
    result.assert_failure()
