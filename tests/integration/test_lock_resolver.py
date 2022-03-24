# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import glob
import hashlib
import os
import re
import subprocess

import pytest

from pex import dist_metadata
from pex.cli.testing import run_pex3
from pex.interpreter import PythonInterpreter
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex_info import PexInfo
from pex.resolve import lockfile
from pex.resolve.locked_resolve import LockedRequirement
from pex.testing import make_env, run_pex_command
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper

if TYPE_CHECKING:
    from typing import Any, Mapping, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def project_name_and_version(path):
    # type: (str) -> Tuple[ProjectName, Version]

    name_and_version = dist_metadata.project_name_and_version(path)
    assert name_and_version is not None
    return ProjectName(name_and_version.project_name), Version(name_and_version.version)


def index_pex_distributions(pex_file):
    # type: (str) -> Mapping[ProjectName, Version]

    return dict(
        project_name_and_version(location) for location in PexInfo.from_pex(pex_file).distributions
    )


def index_lock_artifacts(lock_file):
    # type: (str) -> Mapping[ProjectName, LockedRequirement]

    lock = lockfile.load(lock_file)
    assert 1 == len(lock.locked_resolves)
    locked_resolve = lock.locked_resolves[0]
    return {
        locked_requirement.pin.project_name: locked_requirement
        for locked_requirement in locked_resolve.locked_requirements
    }


@pytest.fixture(scope="module")
def requests_lock_strict(tmpdir_factory):
    # type: (Any) -> str

    lock = os.path.join(str(tmpdir_factory.mktemp("locks")), "requests.lock")
    # N.B.: requests 2.25.1 is known to work with all versions of Python Pex supports.
    run_pex3("lock", "create", "--style", "strict", "requests==2.25.1", "-o", lock).assert_success()
    return lock


def test_strict_basic(
    tmpdir,  # type: Any
    requests_lock_strict,  # type: str
):
    # type: (...) -> None

    requests_pex = os.path.join(str(tmpdir), "requests.pex")
    run_pex_command(
        args=[
            "--lock",
            requests_lock_strict,
            "requests",
            "-o",
            requests_pex,
            "--",
            "-c",
            "import requests",
        ]
    ).assert_success()

    pex_distributions = index_pex_distributions(requests_pex)
    requests_version = pex_distributions.get(ProjectName("requests"))
    assert (
        requests_version is not None
    ), "Expected the requests pex to contain the requests distribution."

    assert (
        dict(
            (project_name, locked_requirement.pin.version)
            for project_name, locked_requirement in index_lock_artifacts(
                requests_lock_strict
            ).items()
        )
        == pex_distributions
    )


def test_subset(
    tmpdir,  # type: Any
    requests_lock_strict,  # type: str
):
    # type: (...) -> None

    urllib3_pex = os.path.join(str(tmpdir), "urllib3.pex")

    def args(*requirements):
        return (
            ["--lock", requests_lock_strict, "-o", urllib3_pex]
            + list(requirements)
            + ["--", "-c", "import urllib3"]
        )

    run_pex_command(args("urllib3")).assert_success()
    pex_distributions = index_pex_distributions(urllib3_pex)
    assert ProjectName("urllib3") in pex_distributions
    for project in ("requests", "idna", "chardet", "certifi"):
        assert ProjectName(project) not in pex_distributions

    # However, if no requirements are specified, resolve the entire lock.
    run_pex_command(args()).assert_success()
    pex_distributions = index_pex_distributions(urllib3_pex)
    for project in ("requests", "urllib3", "idna", "chardet", "certifi"):
        assert ProjectName(project) in pex_distributions


def test_empty_lock_issue_1659(tmpdir):
    # type: (Any) -> None
    lock = os.path.join(str(tmpdir), "empty.lock")
    run_pex3("lock", "create", "--style", "strict", "-o", lock).assert_success()
    run_pex_command(["--lock", lock, "--", "-c", "print('hello')"]).assert_success()


@attr.s(frozen=True)
class LockAndRepo(object):
    lock_file = attr.ib()  # type: str
    find_links_repo = attr.ib()  # type: str


@pytest.fixture(scope="module")
def requests_tool_pex(
    tmpdir_factory,  # type: Any
    requests_lock_strict,  # type: str
):
    # type: (...) -> str

    requests_pex = os.path.join(str(tmpdir_factory.mktemp("tool")), "requests.pex")
    run_pex_command(
        args=["--lock", requests_lock_strict, "--include-tools", "requests", "-o", requests_pex]
    ).assert_success()
    return requests_pex


@pytest.fixture
def requests_lock_findlinks(
    tmpdir_factory,  # type: Any
    requests_tool_pex,  # type: str
):
    # type: (...) -> LockAndRepo

    find_links_repo = str(tmpdir_factory.mktemp("repo"))
    subprocess.check_call(
        args=[requests_tool_pex, "repository", "extract", "-f", find_links_repo],
        env=make_env(PEX_TOOLS=1),
    )
    lock = os.path.join(str(tmpdir_factory.mktemp("locks")), "requests-find-links.lock")
    run_pex3(
        "lock",
        "create",
        "--style",
        "strict",
        "--no-pypi",
        "-f",
        find_links_repo,
        "requests",
        "-o",
        lock,
    ).assert_success()
    return LockAndRepo(lock_file=lock, find_links_repo=find_links_repo)


def test_corrupt_artifact(
    tmpdir,  # type: Any
    requests_lock_findlinks,  # type: LockAndRepo
):
    # type: (...) -> None

    listing = glob.glob(os.path.join(requests_lock_findlinks.find_links_repo, "requests-*"))
    assert 1 == len(listing)
    requests_distribution = listing[0]
    with open(requests_distribution, "ab") as fp:
        fp.write(b"corrupted")

    locked_requirement = index_lock_artifacts(requests_lock_findlinks.lock_file)[
        ProjectName("requests")
    ]
    algorithm = locked_requirement.artifact.fingerprint.algorithm
    expected_hash = locked_requirement.artifact.fingerprint.hash
    actual_hash = CacheHelper.hash(requests_distribution, digest=hashlib.new(algorithm))

    pex_file = os.path.join(str(tmpdir), "pex.file")
    # The Pex cache should save us from downloading the corrupt artifact.
    run_pex_command(
        args=["--lock", requests_lock_findlinks.lock_file, "requests", "-o", pex_file]
    ).assert_success()

    # With the cache cleared (disabled), we're forced to download the artifact and should find it
    # corrupted.
    result = run_pex_command(
        args=[
            "--lock",
            requests_lock_findlinks.lock_file,
            "--disable-cache",
            "requests",
            "-o",
            pex_file,
        ]
    )
    result.assert_failure()

    assert (
        "There was 1 error downloading required artifacts:\n"
        "1. requests 2.25.1 from file://{requests_distribution}\n"
        "    Expected {algorithm} hash of {expected_hash} when downloading requests but hashed to "
        "{actual_hash}.".format(
            requests_distribution=requests_distribution,
            algorithm=algorithm,
            expected_hash=expected_hash,
            actual_hash=actual_hash,
        )
    ) in result.error, result.error


def test_unavailable_artifacts(
    tmpdir,  # type: Any
    requests_lock_findlinks,  # type: LockAndRepo
):
    # type: (...) -> None

    listing = glob.glob(os.path.join(requests_lock_findlinks.find_links_repo, "requests-*"))
    assert 1 == len(listing)
    requests_distribution = listing[0]
    os.unlink(requests_distribution)

    pex_file = os.path.join(str(tmpdir), "pex.file")
    # The Pex cache should save us from downloading the unavailable artifact.
    run_pex_command(
        args=["--lock", requests_lock_findlinks.lock_file, "requests", "-o", pex_file]
    ).assert_success()

    # With the cache cleared (disabled), we're forced to download the artifact and should find it
    # missing.
    result = run_pex_command(
        args=[
            "--lock",
            requests_lock_findlinks.lock_file,
            "--disable-cache",
            "requests",
            "-o",
            pex_file,
        ]
    )
    result.assert_failure()

    assert re.search(
        r"There was 1 error downloading required artifacts:\n"
        r"1\. requests 2\.25\.1 from file://{requests_distribution}\n"
        r"    .* No such file or directory: .*'{requests_distribution}'>".format(
            requests_distribution=re.escape(requests_distribution)
        ),
        result.error,
        re.MULTILINE,
    )


@pytest.fixture(scope="module")
def requests_lock_universal(tmpdir_factory):
    # type: (Any) -> str

    lock = os.path.join(str(tmpdir_factory.mktemp("locks")), "requests-universal.lock")
    run_pex3(
        "lock", "create", "--style", "universal", "requests[security]==2.25.1", "-o", lock
    ).assert_success()
    return lock


def test_multiplatform(
    tmpdir,  # type: Any
    requests_lock_universal,  # type: str
    py37,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    pex_file = os.path.join(str(tmpdir), "pex.file")
    run_pex_command(
        args=[
            "--python",
            py37.binary,
            "--python",
            py310.binary,
            "--lock",
            requests_lock_universal,
            "requests[security]",
            "-o",
            pex_file,
        ]
    ).assert_success()

    check_command = [pex_file, "-c", "import requests"]
    py37.execute(check_command)
    py310.execute(check_command)
