# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import filecmp
import os.path
import shutil
import subprocess
import sys
import tempfile
from textwrap import dedent

import colors
import pytest

from pex.cli.testing import run_pex3
from pex.common import safe_open
from pex.compatibility import PY2, urlparse
from pex.resolve import lockfile
from pex.resolve.locked_resolve import VCSArtifact
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class TestTool(object):
    tmpdir = attr.ib()  # type: str

    @property
    def pex_root(self):
        # type: () -> str
        return os.path.join(self.tmpdir, "pex_root")

    def create_lock(self, *args):
        # type: (*str) -> str
        lock = tempfile.mktemp(prefix="lock.", dir=self.tmpdir)
        run_pex3("lock", "create", "--pex-root", self.pex_root, "-o", lock, *args).assert_success()
        return lock

    def create_pex(
        self,
        lock,  # type: str
        *args  # type: str
    ):
        # type: (...) -> str
        pex = tempfile.mktemp(suffix=".pex", dir=self.tmpdir)
        run_pex_command(
            args=[
                "--pex-root",
                self.pex_root,
                "--runtime-pex-root",
                self.pex_root,
                "--lock",
                lock,
                "-o",
                pex,
            ]
            + list(args)
        ).assert_success()
        return pex

    def create_locked_pex(self, *lock_args):
        # type: (*str) -> str
        return self.create_pex(self.create_lock(*lock_args))


@pytest.fixture
def test_tool(tmpdir):
    # type: (Any) -> TestTool
    return TestTool(str(tmpdir))


def test_vcs_direct_reference(test_tool):
    # type: (TestTool) -> None

    pex = test_tool.create_locked_pex(
        "ansicolors @ git+https://github.com/jonathaneunice/colors.git@c965f5b9"
    )

    assert (
        colors.cyan("Miles Davis")
        == subprocess.check_output(
            args=[pex, "-c", "import colors; print(colors.cyan('Miles Davis'))"]
        )
        .decode("utf-8")
        .strip()
    )


def test_vcs_pip_proprietary(test_tool):
    # type: (TestTool) -> None

    pex = test_tool.create_locked_pex(
        "git+https://github.com/jonathaneunice/colors.git@c965f5b9#egg=ansicolors"
    )

    assert (
        colors.magenta("Alecia Beth Moore")
        == subprocess.check_output(
            args=[pex, "-c", "import colors; print(colors.magenta('Alecia Beth Moore'))"]
        )
        .decode("utf-8")
        .strip()
    )


def test_vcs_equivalence(test_tool):
    # type: (TestTool) -> None

    lock1 = test_tool.create_lock(
        "ansicolors @ git+https://github.com/jonathaneunice/colors.git@c965f5b9"
    )
    lock2 = test_tool.create_lock(
        "git+https://github.com/jonathaneunice/colors.git@c965f5b9#egg=ansicolors"
    )

    assert lock1 != lock2, "Expected two different lock files."

    def extract_single_vcs_artifact(lock):
        # type: (str) -> VCSArtifact
        lock_file = lockfile.load(lock)

        assert 1 == len(lock_file.locked_resolves)
        locked_resolve = lock_file.locked_resolves[0]

        assert 1 == len(locked_resolve.locked_requirements)
        locked_requirement = locked_resolve.locked_requirements[0]

        assert 0 == len(locked_requirement.additional_artifacts)
        assert isinstance(locked_requirement.artifact, VCSArtifact)
        return locked_requirement.artifact

    vcs_artifact1 = extract_single_vcs_artifact(lock1)
    vcs_artifact2 = extract_single_vcs_artifact(lock2)

    assert vcs_artifact1.fingerprint == vcs_artifact2.fingerprint, (
        "We expect locking using a direct reference requirement or a Pip proprietary VCS "
        "requirement for the same VCS revision will produce the same locked VCS archive"
    )
    assert vcs_artifact1.url != vcs_artifact2.url, "Expected two different lock URLs."
    assert "" == urlparse.urlparse(vcs_artifact1.url).fragment
    assert {"egg": ["ansicolors"]} == urlparse.parse_qs(
        urlparse.urlparse(vcs_artifact2.url).fragment
    )


@pytest.mark.skipif(sys.version_info[:2] < (3, 6), reason="The library under test uses f-strings.")
def test_subdir(test_tool):
    # type: (TestTool) -> None

    # This is a trick you cannot do with a direct reference VCS URL.
    pex = test_tool.create_locked_pex(
        "git+https://github.com/SerialDev/sdev_py_utils.git@bd4d36a0"
        "#egg=sdev_logging_utils&subdirectory=sdev_logging_utils"
    )
    assert (
        subprocess.check_output(
            args=[pex, "-c", "import sdev_logging_utils; print(sdev_logging_utils.__file__)"]
        )
        .decode("utf-8")
        .startswith(os.path.join(test_tool.pex_root, "installed_wheels"))
    )


def test_vcs_fingerprint_stability(test_tool):
    # type: (TestTool) -> None

    lock1 = test_tool.create_lock(
        "git+https://github.com/VaasuDevanS/cowsay-python@v3.0#egg=cowsay"
    )
    shutil.rmtree(test_tool.pex_root)
    lock2 = test_tool.create_lock(
        "git+https://github.com/VaasuDevanS/cowsay-python@v3.0#egg=cowsay"
    )

    assert lock1 != lock2, "Expected two different lock files."
    assert filecmp.cmp(
        lock1, lock2, shallow=False
    ), "Expected the same lockfile contents; i.e.: a stable VCS archive hash."


def test_vcs_transitive(
    tmpdir,  # type: Any
    test_tool,  # type: TestTool
):
    # type: (...) -> None

    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "poetry.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import colors


                def third_worst():
                    print(colors.green("Prostetnic Vogon Jeltz"))
                """
            )
        )
    with safe_open(os.path.join(src, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = poetry
                version = 0.0.1

                [options]
                py_modules =
                    poetry

                install_requires =
                    ansicolors @ git+https://github.com/jonathaneunice/colors.git@c965f5b9

                [options.entry_points]
                console_scripts =
                    recite = poetry:third_worst
                """
            )
        )
    with safe_open(os.path.join(src, "setup.py"), "w") as fp:
        fp.write("from setuptools import setup; setup()")

    subprocess.check_call(args=["git", "init", "-b", "Golgafrincham", src])
    subprocess.check_call(args=["git", "config", "user.email", "forty@two.com"], cwd=src)
    subprocess.check_call(args=["git", "config", "user.name", "Douglas Adams"], cwd=src)
    subprocess.check_call(args=["git", "add", "."], cwd=src)
    subprocess.check_call(args=["git", "commit", "-m", "Only commit."], cwd=src)

    lock = test_tool.create_lock("git+file://{src}#egg=poetry".format(src=src))
    pex = test_tool.create_pex(lock, "-c", "recite")
    assert (
        colors.green("Prostetnic Vogon Jeltz")
        == subprocess.check_output(args=[pex]).decode("utf-8").strip()
    )
