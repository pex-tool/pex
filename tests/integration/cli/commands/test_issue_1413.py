# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
import subprocess

import pytest

from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import LockedRequirement
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.path_mappings import PathMapping, PathMappings
from pex.resolve.resolved_requirement import ArtifactURL, Pin
from pex.typing import TYPE_CHECKING
from testing import make_env, run_pex_command
from testing.cli import run_pex3
from testing.pytest.tmp import Tempdir, TempdirFactory

if TYPE_CHECKING:
    from typing import Any


@pytest.fixture(scope="module")
def td(
    tmpdir_factory,  # type: TempdirFactory
    request,  # type: Any
):
    # type: (...) -> Tempdir
    return tmpdir_factory.mktemp("td", request=request)


@pytest.fixture(scope="module")
def find_links_repo(td):
    # type: (Any) -> str
    ansicolors_seed_pex = str(td.join("ansicolors-seed.pex"))
    run_pex_command(
        args=["ansicolors==1.1.8", "-o", ansicolors_seed_pex, "--include-tools"]
    ).assert_success()

    find_links = str(td.join("find-links", "repo"))
    subprocess.check_call(
        args=[ansicolors_seed_pex, "repository", "extract", "-f", find_links],
        env=make_env(PEX_TOOLS=1),
    )
    assert 1 == len(os.listdir(find_links))
    return find_links


FIND_LINKS_NAME = "FL"


def create_path_mapping_option_value(path):
    # type: (str) -> str
    return "{name}|{path}|The local find links repo path.".format(name=FIND_LINKS_NAME, path=path)


def create_path_mappings(path):
    # type: (str) -> PathMappings
    return PathMappings((PathMapping(name=FIND_LINKS_NAME, path=path),))


@pytest.fixture(scope="module")
def lock(
    td,  # type: Any
    find_links_repo,  # type: str
):
    # type: (...) -> str
    lock = str(td.join("lock"))
    path_mapping = create_path_mapping_option_value(find_links_repo)
    run_pex3(
        "lock",
        "create",
        "--no-pypi",
        "-f",
        find_links_repo,
        "--path-mapping",
        path_mapping,
        "ansicolors",
        "-o",
        lock,
    ).assert_success()
    return lock


def expect_single_ansicolors_requirement(lock_file):
    # type: (Lockfile) -> LockedRequirement
    assert 1 == len(lock_file.locked_resolves)
    assert 1 == len(lock_file.locked_resolves[0].locked_requirements)
    ansicolors_requirement = lock_file.locked_resolves[0].locked_requirements[0]
    assert Pin(ProjectName("ansicolors"), Version("1.1.8")) == ansicolors_requirement.pin
    return ansicolors_requirement


def test_find_links_create(
    tmpdir,  # type: Any
    find_links_repo,  # type: str
    lock,  # type: str
):
    # type: (...) -> None

    lock_file = json_codec.load(lock, path_mappings=create_path_mappings("/re/mapped"))
    ansicolors_requirement = expect_single_ansicolors_requirement(lock_file)
    assert 0 == len(ansicolors_requirement.additional_artifacts)
    assert (
        ArtifactURL.parse("file:///re/mapped/ansicolors-1.1.8-py2.py3-none-any.whl")
        == ansicolors_requirement.artifact.url
    )


def assert_missing_mappings(
    lock,  # type: str
    *lock_args  # type: str
):
    # type: (...) -> None
    result = run_pex3(*lock_args)
    result.assert_failure()
    assert result.error == (
        "The lockfile at {lock} requires specifying a '--path-mapping' value for: FL\n"
        "Given no path mappings.\n"
        "Which left the following path mappings unspecified:\n"
        "FL: The local find links repo path.\n"
        "\n"
        "To fix, add command line options for:\n"
        "--path-mapping 'FL|<path of FL>'\n".format(lock=lock)
    )


def test_find_links_update(
    tmpdir,  # type: Any
    find_links_repo,  # type: str
    lock,  # type: str
):
    # type: (...) -> None

    re_mapped_fl = os.path.join(str(tmpdir), "re", "mapped")
    os.mkdir(os.path.dirname(re_mapped_fl))
    shutil.copytree(find_links_repo, re_mapped_fl)

    lock_update_args = ("lock", "update", lock, "--no-pypi", "-f", re_mapped_fl)
    assert_missing_mappings(lock, *lock_update_args)

    def lock_contents():
        # type: () -> str
        with open(lock) as fp:
            return fp.read()

    original_lock_contents = lock_contents()
    run_pex3(
        *(lock_update_args + ("--path-mapping", create_path_mapping_option_value(re_mapped_fl)))
    ).assert_success()
    assert (
        original_lock_contents == lock_contents()
    ), "Expected a no-op update using the same find links repo at a new location."


def test_find_links_export(
    tmpdir,  # type: Any
    find_links_repo,  # type: str
    lock,  # type: str
):
    # type: (...) -> None

    requirements_lock = os.path.join(str(tmpdir), "requirements.txt")
    lock_export_args = (
        "lock",
        "export",
        lock,
        "-o",
        requirements_lock,
    )
    assert_missing_mappings(lock, *lock_export_args)

    requirements_lock = os.path.join(str(tmpdir), "requirements.txt")
    run_pex3(
        *(lock_export_args + ("--path-mapping", create_path_mapping_option_value(find_links_repo)))
    ).assert_success()

    run_pex_command(
        args=[
            "--no-pypi",
            "-f",
            find_links_repo,
            "-r",
            requirements_lock,
            "--",
            "-c",
            "import colors",
        ]
    ).assert_success()
