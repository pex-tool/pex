# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re
import shutil
import subprocess
import sys
from collections import defaultdict

import pytest

from pex.dist_metadata import ProjectNameAndVersion, Requirement
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from testing import PY39, PY310, PY_VER, data, ensure_python_interpreter, make_env, run_pex_command
from testing.cli import run_pex3
from testing.lock import extract_lock_option_args, index_lock_artifacts

if TYPE_CHECKING:
    from typing import Any, Iterable, List, Mapping


def assert_overrides(
    pex,  # type: str
    expected_overrides,  # type: Iterable[str]
    expected_overridden_dists,  # type: Mapping[str, List[str]]
):
    pex_info = PexInfo.from_pex(pex)
    assert list(sorted(expected_overrides)) == list(sorted(pex_info.overridden))

    dists_to_versions = defaultdict(list)
    for dist in pex_info.distributions:
        project_name_and_version = ProjectNameAndVersion.from_filename(dist)
        dists_to_versions[project_name_and_version.canonicalized_project_name].append(
            project_name_and_version.canonicalized_version
        )

    expected_project_names_to_versions = {
        ProjectName(project_name): [Version(version) for version in sorted(versions)]
        for project_name, versions in expected_overridden_dists.items()
    }
    assert expected_project_names_to_versions == {
        project_name: sorted(versions, key=str)
        for project_name, versions in dists_to_versions.items()
        if project_name in expected_project_names_to_versions
    }, pex_info.dump(indent=2)


skip_unless_compatible_with_requests_2_31_0 = pytest.mark.skipif(
    PY_VER < (3, 7), reason="The requests version tested requires Python `>=3.7`."
)


@skip_unless_compatible_with_requests_2_31_0
def test_override(tmpdir):
    # type: (Any) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[
            "--python",
            sys.executable,
            "--python",
            ensure_python_interpreter(PY310 if PY_VER < (3, 10) else PY39),
            "requests==2.31.0",
            "--override",
            "urllib3==1.21; python_version >= '3.10'",
            "--override",
            "urllib3==1.20; python_version < '3.10'",
            "--override",
            "idna<2.5",
            "-o",
            pex,
        ]
    ).assert_success()

    dists = [
        dist for dist in PEX(pex).resolve() if ProjectName("requests") == dist.metadata.project_name
    ]
    assert 1 == len(dists)
    requests = dists[0]
    request_deps_by_project_name = {dep.project_name: dep for dep in requests.requires()}
    assert (
        Requirement.parse("urllib3<3,>=1.21.1")
        == request_deps_by_project_name[ProjectName("urllib3")]
    ), (
        "Our multiple override test requires requests normally have an urllib3 lower bound of "
        "1.21.1."
    )
    assert (
        Requirement.parse("idna<4,>=2.5") == request_deps_by_project_name[ProjectName("idna")]
    ), "Our single override test requires requests normally have an idna lower bound of 2.5."

    assert_overrides(
        pex,
        expected_overrides=[
            'urllib3==1.21; python_version >= "3.10"',
            'urllib3==1.20; python_version < "3.10"',
            "idna<2.5",
        ],
        expected_overridden_dists={"urllib3": ["1.20", "1.21"], "idna": ["2.4"]},
    )


@skip_unless_compatible_with_requests_2_31_0
def test_pex_repository_override(tmpdir):
    # type: (Any) -> None

    repository_pex = os.path.join(str(tmpdir), "repository.pex")
    run_pex_command(
        args=["requests==2.31.0", "--override", "idna<2.4", "-o", repository_pex]
    ).assert_success()

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=["--pex-repository", repository_pex, "requests", "-o", pex]
    ).assert_success()
    assert_overrides(
        pex, expected_overrides=["idna<2.4"], expected_overridden_dists={"idna": ["2.3"]}
    )


@skip_unless_compatible_with_requests_2_31_0
def test_pre_resolved_dists_override(tmpdir):
    # type: (Any) -> None

    repository_pex = os.path.join(str(tmpdir), "repository.pex")
    run_pex_command(
        args=["requests==2.31.0", "--override", "idna<2.4", "--include-tools", "-o", repository_pex]
    ).assert_success()
    dists = os.path.join(str(tmpdir), "dists")
    subprocess.check_call(
        args=[repository_pex, "repository", "extract", "-f", dists], env=make_env(PEX_TOOLS=1)
    )

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=["--pre-resolved-dists", dists, "requests", "--override", "idna<2.4", "-o", pex]
    ).assert_success()
    assert_overrides(
        pex, expected_overrides=["idna<2.4"], expected_overridden_dists={"idna": ["2.3"]}
    )


REQUESTS_LOCK = data.path("locks", "requests.lock.json")


@pytest.fixture
def requests_lock(tmpdir):
    # type: (Any) -> str

    lock = os.path.join(str(tmpdir), "requests-lock.json")
    shutil.copy(REQUESTS_LOCK, lock)
    return lock


skip_unless_compatible_with_requests_lock = pytest.mark.skipif(
    PY_VER < (3, 7) or PY_VER >= (3, 13), reason="The lock used is for >=3.7,<3.13"
)


@skip_unless_compatible_with_requests_lock
def test_lock_sync_override(
    tmpdir,  # type: Any
    requests_lock,  # type: str
):
    # type: (...) -> None

    index = index_lock_artifacts(requests_lock)
    locked_requests = index[ProjectName("requests")]
    request_deps_by_project_name = defaultdict(list)
    for req in locked_requests.requires_dists:
        request_deps_by_project_name[req.project_name].append(req)
    assert [Requirement.parse("urllib3<3,>=1.21.1")] == request_deps_by_project_name[
        ProjectName("urllib3")
    ], (
        "We expect the locked requests to impose a lower bound of 1.21.1 on urllib3 since we'll "
        "try to edit that lower bound below using `--override`."
    )

    result = run_pex3(
        *(
            ["lock", "sync", "--lock", requests_lock, "--override", "urllib3<1.21.1"]
            + extract_lock_option_args(requests_lock)
        )
    )
    result.assert_success()
    assert "Updates for lock generated by universal:\n" in result.error, result.error
    assert "  Updated urllib3 from 2.0.7 to 1.21\n" in result.error, result.error

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(args=["--lock", requests_lock, "-o", pex]).assert_success()
    assert_overrides(
        pex, expected_overrides=["urllib3<1.21.1"], expected_overridden_dists={"urllib3": ["1.21"]}
    )


@skip_unless_compatible_with_requests_lock
def test_illegal_override(
    tmpdir,  # type: Any
    requests_lock,  # type: str
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(args=["--lock", requests_lock, "--override", "foo", "-o", pex]).assert_failure(
        expected_error_re=".*{expected_message}$".format(
            expected_message=re.escape(
                "The --override option cannot be used when resolving against a lock file. "
                "Only overrides already present in the lock file will be applied.\n"
            )
        ),
        re_flags=re.DOTALL,
    )

    pex_repository = os.path.join(str(tmpdir), "repository.pex")
    run_pex_command(args=["--lock", requests_lock, "-o", pex_repository]).assert_success()
    run_pex_command(
        args=["--pex-repository", requests_lock, "--override", "bar", "-o", pex]
    ).assert_failure(
        expected_error_re=".*{expected_message}$".format(
            expected_message=re.escape(
                "The --override option cannot be used when resolving against a PEX repository. "
                "Only overrides already present in the PEX repository will be applied.\n"
            )
        ),
        re_flags=re.DOTALL,
    )
