# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
from textwrap import dedent

from pex.compatibility import commonpath
from pex.targets import LocalInterpreter
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any, Iterable, Optional


def test_lock_use_no_build_wheel(tmpdir):
    # type: (Any)-> None

    lock = os.path.join(str(tmpdir), "lock")
    run_pex3(
        "lock",
        "create",
        "ansicolors==1.1.8",
        "--only-binary",
        "ansicolors",
        "-o",
        lock,
        "--style",
        "universal",
        "--indent",
        "2",
    ).assert_success()

    def assert_pex_from_lock(
        extra_args=(),  # type: Iterable[str]
        expected_error=None,  # type: Optional[str]
    ):
        # type: (...) -> None

        pex_root = os.path.realpath(os.path.join(str(tmpdir), "pex_root"))
        args = [
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--lock",
            lock,
            "--",
            "-c",
            "import colors, os; print(os.path.realpath(colors.__file__))",
        ]
        result = run_pex_command(args=list(extra_args) + args)
        if expected_error:
            result.assert_failure()
            assert expected_error in result.error
        else:
            result.assert_success()
            assert pex_root == commonpath((pex_root, result.output.strip()))

    assert_pex_from_lock()

    # A redundant --only-binary should not matter.
    assert_pex_from_lock(extra_args=["--only-binary", "ansicolors"])

    # An extraneous --only-build should not matter.
    assert_pex_from_lock(extra_args=["--only-build", "cowsay"])

    # However; a conflicting --only-build should matter.
    assert_pex_from_lock(
        extra_args=["--only-build", "ansicolors"],
        expected_error=dedent(
            """\
            Failed to resolve all requirements for {target_description} from {lock}:

            Configured with:
                build: True
                only_build: ansicolors
                use_wheel: True

            Dependency on ansicolors not satisfied, 1 incompatible candidate found:
            1.) ansicolors 1.1.8 (via: ansicolors==1.1.8) does not have any compatible artifacts:
            """
        ).format(lock=lock, target_description=LocalInterpreter.create().render_description()),
    )
