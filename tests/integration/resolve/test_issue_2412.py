# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import filecmp
import os.path
import re
import shutil
import subprocess
from textwrap import dedent

from colors import color  # vendor:skip

from pex.common import safe_open, touch
from pex.targets import LocalInterpreter
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any, Optional


def test_invalid_project(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    non_project_dir = os.path.join(str(tmpdir), "non-project-dir")
    os.mkdir(non_project_dir)
    run_pex_command(
        args=["--project", pex_project_dir, "--project", non_project_dir]
    ).assert_failure(
        expected_error_re=r".*{message}.*$".format(
            message=re.escape(
                "Found 1 invalid --project specifier:\n"
                "1. The --project {non_project_dir} is not a valid local project "
                "requirement: ".format(non_project_dir=non_project_dir)
            )
        ),
        re_flags=re.DOTALL,
    )

    non_project_file = os.path.join(str(tmpdir), "non-project-file")
    touch(non_project_file)
    run_pex3(
        "lock",
        "create",
        "--project",
        non_project_dir,
        "--project",
        pex_project_dir,
        "--project",
        non_project_file,
    ).assert_failure(
        expected_error_re=r".*{message_part1}.*$.*{message_part2}.*$".format(
            message_part1=re.escape(
                "Found 2 invalid --project specifiers:\n"
                "1. The --project {non_project_dir} is not a valid local project "
                "requirement: ".format(non_project_dir=non_project_dir)
            ),
            message_part2=re.escape(
                "2. The --project {non_project_file} is not a valid local project "
                "requirement: ".format(non_project_file=non_project_file)
            ),
        ),
        re_flags=re.DOTALL | re.MULTILINE,
    )


def test_locked_project(tmpdir):
    # type: (Any) -> None

    project_dir = os.path.join(str(tmpdir), "project")

    def write_speak(fg_color):
        # type: (str) -> None
        with safe_open(os.path.join(project_dir, "speak.py"), "w") as fp:
            fp.write(
                dedent(
                    """\
                    import cowsay
                    try:
                        from colors import color
                    except ImportError:
                        def color(text, **args):
                            return text


                    def tux():
                        cowsay.tux(color("Moo?", fg={fg_color!r}))
                    """
                ).format(fg_color=fg_color)
            )

    def write_setup(cowsay_requirement):
        # type: (str) -> None
        with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
            fp.write(
                dedent(
                    """\
                    from setuptools import setup


                    setup(
                        name="speak",
                        version="0.1",
                        install_requires=[{cowsay_requirement!r}],
                        extras_require={{
                            "color": ["ansicolors"],
                        }},
                        entry_points={{
                            "console_scripts": [
                                "speak = speak:tux",
                            ],
                        }},
                        py_modules=["speak"],
                    )
                    """
                ).format(cowsay_requirement=cowsay_requirement)
            )

    def assert_pex(
        pex,  # type: str
        expected_color=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        assert "| {message} |".format(
            message=color("Moo?", fg=expected_color) if expected_color else "Moo?"
        ) in subprocess.check_output(args=[pex]).decode("utf-8")

    pex_root = os.path.join(str(tmpdir), "pex-root")

    write_speak(fg_color="brown")
    write_setup(cowsay_requirement="cowsay<5")

    project_with_color = "{project_dir}[color]".format(project_dir=project_dir)

    project_lock = os.path.join(str(tmpdir), "project-lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        project_with_color,
        "--indent",
        "2",
        "-o",
        project_lock,
    ).assert_success()
    pex1 = os.path.join(str(tmpdir), "pex1")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--lock",
            project_lock,
            "-c",
            "speak",
            "-o",
            pex1,
        ]
    ).assert_success()
    assert_pex(pex1, expected_color="brown")

    third_party_lock = os.path.join(str(tmpdir), "third-party-lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--project",
        project_with_color,
        "--indent",
        "2",
        "-o",
        third_party_lock,
    ).assert_success()
    pex2 = os.path.join(str(tmpdir), "pex2")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--project",
            project_with_color,
            "--lock",
            third_party_lock,
            "-c",
            "speak",
            "-o",
            pex2,
        ]
    ).assert_success()
    assert_pex(pex2, expected_color="brown")

    # Using `pex --project local/project` should produce identical results to `pex local/project`;
    # the utility of `pex --project` comes only when combined with a lock or PEX repository.
    assert filecmp.cmp(pex1, pex2, shallow=False)

    # Modifying the project should invalidate the full project lock, but work with a `--project`
    # lock.
    write_speak(fg_color="blue")
    shutil.rmtree(pex_root)

    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--lock",
            project_lock,
            "-c",
            "speak",
            "-o",
            pex1,
        ]
    ).assert_failure(
        expected_error_re=(
            r".*{lead_in_message} {sha256_re} when downloading speak but hashed to "
            r"{sha256_re}\.\n$".format(
                lead_in_message=re.escape(
                    "There was 1 error downloading required artifacts:\n"
                    "1. speak 0.1 from file://{project_dir}\n"
                    "    Expected sha256 hash of".format(project_dir=project_dir)
                ),
                sha256_re=r"[a-f0-9]{64}",
            )
        ),
        re_flags=re.DOTALL,
    )

    pex3 = os.path.join(str(tmpdir), "pex3")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--project",
            project_dir,
            "--lock",
            third_party_lock,
            "-c",
            "speak",
            "-o",
            pex3,
        ]
    ).assert_success()
    assert_pex(pex3)

    # If the project is updated in a way incompatible with the lock, building a
    # `pex --project ... --lock ...` should fail.
    write_setup(cowsay_requirement="cowsay==5.0")
    target = LocalInterpreter.create()
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--project",
            project_dir,
            "--lock",
            third_party_lock,
            "-c",
            "speak",
            "-o",
            pex3,
        ]
    ).assert_failure(
        expected_error_re=r".*{message}$".format(
            message=re.escape(
                "Failed to resolve compatible artifacts from lock {lock} for 1 target:\n"
                "1. {target}:\n"
                "    Failed to resolve all requirements for {target_description} from {lock}:\n"
                "\n"
                "Configured with:\n"
                "    build: True\n"
                "    use_wheel: True\n"
                "\n"
                "Dependency on cowsay not satisfied, 1 incompatible candidate found:\n"
                "1.) cowsay 4 does not satisfy the following requirements:\n"
                "    ==5.0 (via: cowsay==5.0)\n".format(
                    lock=third_party_lock,
                    target=target,
                    target_description=target.render_description(),
                )
            )
        ),
        re_flags=re.DOTALL,
    )

    # But syncing the `--project` lock to the modified project should re-right the ship.
    run_pex3(
        "lock",
        "sync",
        "--pex-root",
        pex_root,
        "--project",
        project_with_color,
        "--indent",
        "2",
        "--lock",
        third_party_lock,
    ).assert_success()
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--project",
            project_with_color,
            "--lock",
            third_party_lock,
            "-c",
            "speak",
            "-o",
            pex3,
        ]
    ).assert_success()
    assert_pex(pex3, expected_color="blue")
