# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import re
from textwrap import dedent
from typing import Dict, Sequence

from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.lockfile import json_codec
from pex.third_party.packaging.markers import Marker
from pex.typing import TYPE_CHECKING
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Any, List, Optional, Tuple  # noqa


def assert_split_lock(
    lockfile_path,  # type: str
    cowsay5_marker="platform_machine == 'x86_64'",  # type: str
    cowsay6_marker="platform_machine != 'x86_64'",  # type: str
    additional5_pins=(),  # type: Sequence[Tuple[str, str]]
    additional6_pins=(),  # type: Sequence[Tuple[str, str]]
):
    # type: (...) -> None

    lock = json_codec.load(lockfile_path=lockfile_path)
    assert 2 == len(lock.locked_resolves)

    # N.B.: Marker objects don't implement value equals; so we normalize markers to their string
    # representations for consistent comparison.

    locked_resolve_by_marker = {
        str(locked_resolve.marker): locked_resolve for locked_resolve in lock.locked_resolves
    }

    def index_lock(marker):
        # type: (str) -> Dict[ProjectName, Version]
        return {
            locked_requirement.pin.project_name: locked_requirement.pin.version
            for locked_requirement in locked_resolve_by_marker.pop(
                str(Marker(marker))
            ).locked_requirements
        }

    cowsay5_lock = index_lock(cowsay5_marker)
    assert 1 + len(additional5_pins) == len(cowsay5_lock)
    assert Version("5") == cowsay5_lock.pop(ProjectName("cowsay"))
    for project_name, version in additional5_pins:
        assert Version(version) == cowsay5_lock.pop(ProjectName(project_name))

    cowsay6_lock = index_lock(cowsay6_marker)
    assert 1 + len(additional6_pins) == len(cowsay6_lock)
    assert Version("6") == cowsay6_lock.pop(ProjectName("cowsay"))
    for project_name, version in additional6_pins:
        assert Version(version) == cowsay6_lock.pop(ProjectName(project_name))


def test_split_positional_requirements(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--style",
        "universal",
        "cowsay==5; platform_machine == 'x86_64'",
        "cowsay==6; platform_machine != 'x86_64'",
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()
    assert_split_lock(lock)


def test_split_requirements_txt(tmpdir):
    # type: (Tempdir) -> None

    requirements_txt = tmpdir.join("requirements.txt")
    with open(requirements_txt, "w") as fp:
        fp.write(
            dedent(
                """\
                # Header comments.
                
                # Old.
                cowsay==5; platform_machine == 'x86_64'
                
                # New.
                cowsay==6; platform_machine != 'x86_64'
                """
            )
        )

    pex_root = tmpdir.join("pex-root")
    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--style",
        "universal",
        "-r",
        requirements_txt,
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()
    assert_split_lock(lock)


def test_split_mixed_positional_requirements_and_requirements_txt(tmpdir):
    # type: (Tempdir) -> None

    requirements_txt = tmpdir.join("requirements.txt")
    with open(requirements_txt, "w") as fp:
        fp.write(
            dedent(
                """\
                # Header comments.
                
                # Multiline.
                cowsay==6; \\
                    platform_machine != 'x86_64'
                """
            )
        )

    pex_root = tmpdir.join("pex-root")
    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--style",
        "universal",
        "cowsay==5; platform_machine == 'x86_64'",
        "-r",
        requirements_txt,
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()
    assert_split_lock(lock)


def test_split_warn(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--style",
        "universal",
        "cowsay==5; platform_machine >= 'x86_64'",
        "cowsay==6; platform_machine != 'x86_64'",
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success(
        expected_error_re=r"^.*{warning}.*$".format(
            warning=re.escape(
                "PEXWarning: Cannot split universal lock on all clauses of the marker in "
                "`cowsay==5; platform_machine >= 'x86_64'`.\n"
                "The clause `platform_machine >= x86_64` uses comparison `>=` but only `==` and "
                "`!=` are supported for splitting on 'platform_machine'.\n"
                "Ignoring this clause in split calculations; lock results may be unexpected."
            )
        ),
        re_flags=re.DOTALL,
    )
    assert_split_lock(lock, cowsay5_marker="platform_machine >= 'x86_64'")


def test_split_merge_non_conflicting(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--style",
        "universal",
        "cowsay==5; platform_machine == 'x86_64'",
        "cowsay==6; platform_machine != 'x86_64'",
        "ansicolors==1.1.7; platform_machine == 'x86_64'",
        "ansicolors==1.1.8; platform_machine != 'x86_64'",
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()
    assert_split_lock(
        lock, additional5_pins=[("ansicolors", "1.1.7")], additional6_pins=[("ansicolors", "1.1.8")]
    )
