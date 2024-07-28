# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re
from textwrap import dedent

import pytest

from pex import targets
from pex.build_system import pep_517
from pex.common import safe_open
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.result import try_
from pex.typing import TYPE_CHECKING
from testing import PY_VER, IntegResults, run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


@pytest.fixture
def feast_simulator_project(tmpdir):
    # type: (Any) -> str
    project_dir = os.path.join(str(tmpdir), "feast-simulator")
    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup


                setup(
                    name="feast-simulator",
                    version="0.1.0",
                    install_requires=["ansicolors<1.1.9,>=1.0.*"]
                )
                """
            )
        )
    return project_dir


skip_if_setuptools_too_old = pytest.mark.skipif(
    PY_VER < (3, 7),
    reason=(
        "The setuptools / packaging compatible with Python<3.7 does not fail to process the bad "
        "metadata used in this test."
    ),
)


def assert_local_project_build_failure_message(result):
    # type: (IntegResults) -> None
    result.assert_failure(
        expected_error_re=(
            r".*"
            r"^\s*pip:.*(?:{cause_distribution_hint_one}|{cause_distribution_hint_two}).*"
            r"(?:{reason_one}|{reason_two}).*$"
            r".*"
            r"^\s*pip:.*{requirement}$"
            r".*"
        ).format(
            # N.B.: We have two versions of cause and reason to account for permutations of Pip,
            # setuptools and package resources messages which all intermix here.
            cause_distribution_hint_one=re.escape(
                "Failed to parse a requirement of feast-simulator 0.1.0"
            ),
            cause_distribution_hint_two=re.escape("error in feast-simulator setup command:"),
            reason_one=re.escape(
                "'install_requires' must be a string or list of strings containing valid "
                "project/version requirement specifiers"
            ),
            reason_two=re.escape(".* suffix can only be used with `==` or `!=` operators"),
            requirement=re.escape("ansicolors<1.1.9,>=1.0.*"),
        ),
        re_flags=re.DOTALL | re.MULTILINE,
    )


@skip_if_setuptools_too_old
def test_metadata_gen_from_local_project_failure_lock(
    tmpdir,  # type: Any
    feast_simulator_project,  # type: str
):
    # type: (...) -> None
    assert_local_project_build_failure_message(
        run_pex3("lock", "create", feast_simulator_project, "-o", os.path.join(str(tmpdir), "lock"))
    )


@skip_if_setuptools_too_old
def test_metadata_gen_from_local_project_failure_build_pex(
    tmpdir,  # type: Any
    feast_simulator_project,  # type: str
):
    # type: (...) -> None
    assert_local_project_build_failure_message(
        run_pex_command(
            args=[feast_simulator_project, "-o", (os.path.join(str(tmpdir), "pex"))], quiet=True
        )
    )


@pytest.fixture
def feast_simulator_sdist(
    tmpdir,  # type: Any
    feast_simulator_project,  # type: str
):
    # type: (...) -> str
    with safe_open(os.path.join(feast_simulator_project, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                build-backend = "setuptools.build_meta"

                # N.B.: We need an older setuptools to be able to build an sdist containing bad
                # metadata. With setuptools 67.0.0, packaging 23.0 is vendored with strict
                # requirement parsing that leads to setuptools refusing to build the sdist at all.
                # See: https://setuptools.pypa.io/en/stable/history.html#v67-0-0
                requires = ["setuptools<67"]
                """
            )
        )

    return str(
        try_(
            pep_517.build_sdist(
                project_directory=feast_simulator_project,
                dist_dir=os.path.join(str(tmpdir), "build"),
                target=targets.current(),
                resolver=ConfiguredResolver.default(),
            )
        )
    )


def assert_dist_build_failure_message(result):
    # type: (IntegResults) -> None
    result.assert_failure(
        expected_error_re=(
            r".*"
            r"^\s*pip:.*{cause_distribution_hint}.*$"
            r".*"
            r"^\s*pip:.*{reason}$"
            r".*"
            r"^\s*pip:.*{requirement}$"
            r".*"
        ).format(
            cause_distribution_hint=re.escape("feast_simulator-0.1.0.dist-info"),
            reason=re.escape(".* suffix can only be used with `==` or `!=` operators"),
            requirement=re.escape("ansicolors<1.1.9,>=1.0.*"),
        ),
        re_flags=re.DOTALL | re.MULTILINE,
    )


@skip_if_setuptools_too_old
def test_metadata_gen_from_dist_failure_lock(
    tmpdir,  # type: Any
    feast_simulator_sdist,  # type: str
):
    # type: (...) -> None
    lock = os.path.join(str(tmpdir), "lock")
    assert_dist_build_failure_message(run_pex3("lock", "create", feast_simulator_sdist, "-o", lock))


@skip_if_setuptools_too_old
def test_metadata_gen_from_dist_failure_build_pex(
    tmpdir,  # type: Any
    feast_simulator_sdist,  # type: str
):
    # type: (...) -> None
    pex = os.path.join(str(tmpdir), "pex")
    assert_dist_build_failure_message(
        run_pex_command(args=[feast_simulator_sdist, "-o", pex], quiet=True)
    )
