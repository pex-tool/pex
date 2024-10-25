# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import re
import shutil
from textwrap import dedent
from typing import Dict, Set, Tuple

import pytest

from pex.atomic_directory import atomic_directory
from pex.common import safe_mkdir
from pex.dist_metadata import Requirement
from pex.pep_427 import InstallableType
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.path_mappings import PathMapping, PathMappings
from pex.resolve.resolved_requirement import Pin
from pex.resolve.resolvers import Resolver
from pex.typing import TYPE_CHECKING
from testing import IntegResults, built_wheel, re_exact
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any, List, Optional, Protocol

    import attr  # vendor:skip

    class RunLockUpdate(Protocol):
        def __call__(
            self,
            *args,  # type: str
            **popen_kwargs  # type: Any
        ):
            # type: (...) -> IntegResults
            pass

else:
    from pex.third_party import attr


@attr.s(frozen=True)
class FindLinksRepo(object):
    @classmethod
    def create(cls, path):
        # type: (str) -> FindLinksRepo
        safe_mkdir(path, clean=True)
        return cls(path)

    path = attr.ib()  # type: str

    def host(self, distribution):
        # type: (str) -> None
        shutil.copy(distribution, os.path.join(self.path, os.path.basename(distribution)))

    def make_wheel(
        self,
        project_name,  # type: str
        version,  # type: str
        requirements=None,  # type: Optional[List[str]]
    ):
        # type: (...) -> None
        with built_wheel(
            name=project_name, version=version, install_reqs=requirements, universal=True
        ) as wheel:
            self.host(wheel)


def populate_find_links_repo_initial(
    find_links_repo,  # type: FindLinksRepo
    resolver,  # type: Resolver
):
    # type: (...) -> None

    # N.B.: Since we are setting up a find links repo for offline lock resolves, we grab one
    # distribution online to allow the current Pip version to bootstrap itself if needed.
    result = resolver.resolve_requirements(
        ["ansicolors==1.1.8", "cowsay==6.0.0"], result_type=InstallableType.WHEEL_FILE
    )
    for resolved_distribution in result.distributions:
        find_links_repo.host(resolved_distribution.distribution.location)

    find_links_repo.make_wheel("proj-c", "1")
    find_links_repo.make_wheel("proj-b", "1", requirements=["proj-a", "proj-c", "cowsay"])
    find_links_repo.make_wheel("proj-a", "1", requirements=["proj-c", "ansicolors"])
    find_links_repo.make_wheel("proj-a", "1.1", requirements=["proj-c", "ansicolors"])


def populate_find_links_repo_additional(find_links_repo):
    # type: (FindLinksRepo) -> None
    find_links_repo.make_wheel("proj-a", "2", requirements=["ansicolors"])
    find_links_repo.make_wheel("proj-b", "2", requirements=["proj-c"])


_FIND_LINKS_REPO_PATH_MAPPING_NAME = "FL"


@pytest.fixture
def path_mappings(tmpdir):
    # type: (Any) -> PathMappings
    return PathMappings(
        (PathMapping(os.path.join(str(tmpdir), "arbitrary"), _FIND_LINKS_REPO_PATH_MAPPING_NAME),)
    )


@pytest.fixture(scope="session")
def lock_session_fixtures(shared_integration_test_tmpdir):
    # type: (str) -> Tuple[str, PipVersionValue, RunLockUpdate]

    pip_version = PipVersion.DEFAULT

    def repo_args(find_links_dir):
        # type: (str) -> List[str]
        return [
            "--no-pypi",
            "--find-links",
            find_links_dir,
            "--path-mapping",
            "{name}|{find_links}|Test find links repo".format(
                name=_FIND_LINKS_REPO_PATH_MAPPING_NAME, find_links=find_links_dir
            ),
        ]

    test_lock_update_chroot = os.path.join(
        shared_integration_test_tmpdir, "test_lock_update_chroot"
    )
    with atomic_directory(test_lock_update_chroot) as chroot:
        if not chroot.is_finalized():
            resolver = ConfiguredResolver.version(pip_version)

            find_links = os.path.join(chroot.work_dir, "find_links")
            find_links_repo = FindLinksRepo.create(find_links)

            # Control an initial lock.
            populate_find_links_repo_initial(find_links_repo, resolver)
            run_pex3(
                *(
                    [
                        "lock",
                        "create",
                        "--pip-version",
                        str(pip_version),
                        "--resolver-version",
                        "pip-2020-resolver",
                    ]
                    + repo_args(find_links)
                    + [
                        "--style",
                        "universal",
                        "proj-a",
                        "proj-b==1.*",
                        "--indent",
                        "2",
                        "-o",
                        os.path.join(chroot.work_dir, "lock.json"),
                    ]
                )
            ).assert_success()

            # Now advance the state of the work with new versions of projects released.
            populate_find_links_repo_additional(find_links_repo)

    lock = os.path.join(test_lock_update_chroot, "lock.json")

    def run_lock_update(
        *args,  # type: str
        **popenkwargs  # type: Any
    ):
        # type: (...) -> IntegResults
        all_args = ["lock", "update"]
        all_args.extend(repo_args(os.path.join(test_lock_update_chroot, "find_links")))
        all_args.extend(args)
        return run_pex3(*all_args, **popenkwargs)

    return lock, pip_version, run_lock_update


@pytest.fixture
def lock_fixtures(
    tmpdir,  # type: Any
    lock_session_fixtures,  # type: Tuple[str, PipVersionValue, RunLockUpdate]
):
    # type: (...) -> Tuple[str, PipVersionValue, RunLockUpdate]
    lock, pip_version, run_lock_update = lock_session_fixtures

    lock_copy = os.path.join(str(tmpdir), os.path.basename(lock))
    shutil.copy(lock, lock_copy)

    def run_lock_update_on_copy(
        *args,  # type: str
        **popenkwargs  # type: Any
    ):
        # type: (...) -> IntegResults
        all_args = list(args)
        all_args.append(lock_copy)
        return run_lock_update(*all_args, **popenkwargs)

    return lock_copy, pip_version, run_lock_update_on_copy


@pytest.fixture
def lock(lock_fixtures):
    # type: (Tuple[str, PipVersionValue, RunLockUpdate]) -> str
    lock, _, _ = lock_fixtures
    return lock


@pytest.fixture
def pip_version(lock_fixtures):
    # type: (Tuple[str, PipVersionValue, RunLockUpdate]) -> PipVersionValue
    _, pip_version, _ = lock_fixtures
    return pip_version


@pytest.fixture
def run_lock_update(lock_fixtures):
    # type: (Tuple[str, PipVersionValue, RunLockUpdate]) -> RunLockUpdate
    _, _, run_lock_update = lock_fixtures
    return run_lock_update


def test_lock_update_invalid(run_lock_update):
    # type: (RunLockUpdate) -> None
    run_lock_update("-p", "<invalid>").assert_failure(
        expected_error_re=re.escape("Failed to parse project requirement to update '<invalid>': ")
    )


def test_lock_update_nominal(run_lock_update):
    # type: (RunLockUpdate) -> None
    run_lock_update("-p", "proj-a").assert_success(
        expected_error_re=re_exact(
            dedent(
                """\
                Updates for lock generated by universal:
                  Updated proj-a from 1.1 to 2
                """
            )
        )
    )


def test_lock_update_downgrade(run_lock_update):
    # type: (RunLockUpdate) -> None
    run_lock_update("-p", "proj-a<1.1").assert_success(
        expected_error_re=re_exact(
            dedent(
                """\
                Updates for lock generated by universal:
                  Updated proj-a from 1.1 to 1
                Updates to lock input constraints:
                  Added 'proj-a<1.1'
                """
            )
        )
    )


def test_lock_update_conflict(
    run_lock_update,  # type: RunLockUpdate
    pip_version,  # type: PipVersionValue
):
    # type: (...) -> None
    run_lock_update("-p", "proj-b>=2").assert_failure(
        expected_error_re=r".*{header_info}.*{error_message}.*".format(
            header_info=re.escape(
                dedent(
                    """\
                    Given the lock requirements:
                    proj-a
                    proj-b==1.*

                    The following lock update constraints could not all be satisfied:
                    ansicolors==1.1.8
                    cowsay==6
                    proj-a==1.1
                    proj-b>=2
                    proj-c==1
                    """
                )
            ),
            # N.B.: The nice conflict messages are only produced by all the non-vendored Pip versions Pex supports.
            error_message=(
                ""
                if pip_version is PipVersion.VENDORED
                else re.escape(
                    dedent(
                        """\
                        pip:  The conflict is caused by:
                        pip:      The user requested proj-b==1.*
                        pip:      The user requested (constraint) proj-b>=2
                        """
                    )
                )
            ),
        ),
        re_flags=re.DOTALL,
    )


def test_lock_update_replace(run_lock_update):
    # type: (RunLockUpdate) -> None

    # N.B.: This is a conflict specified as a normal project update (see `test_lock_update_conflict` above); the `=`
    # replace directive is what makes this work.
    run_lock_update("-R", "proj-b>=2").assert_success(
        expected_error_re=re_exact(
            dedent(
                """\
                Updates for lock generated by universal:
                  Updated proj-b from 1 to 2
                Updates to lock input requirements:
                  Updated 'proj-b==1.*' to 'proj-b>=2'
                """
            )
        )
    )


def test_lock_update_replace_invalid(run_lock_update):
    # type: (RunLockUpdate) -> None
    run_lock_update("-R", "<invalid>").assert_failure(
        expected_error_re=re.escape("Failed to parse replacement project requirement '<invalid>': ")
    )


def test_lock_update_delete_invalid(run_lock_update):
    # type: (RunLockUpdate) -> None
    run_lock_update("-d", "valid>1.0").assert_failure(
        expected_error_re=re_exact(
            "Failed to parse project name to delete: The given project name 'valid>1.0' is not a valid. "
            "It must conform to the regex '^([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])$' as specified in "
            "https://peps.python.org/pep-0508/#names"
        )
    )


def index_requirements(lockfile):
    # type: (Lockfile) -> Dict[ProjectName, Requirement]
    return {req.project_name: req for req in lockfile.requirements}


def locked_requirement_pins(lockfile):
    # type: (Lockfile) -> Set[Pin]
    assert len(lockfile.locked_resolves) == 1
    locked_resolve = lockfile.locked_resolves[0]
    return {locked_requirement.pin for locked_requirement in locked_resolve.locked_requirements}


def pin(
    project_name,  # type: str
    version,  # type: str
):
    # type: (...) -> Pin
    return Pin(ProjectName(project_name), Version(version))


def test_lock_update_delete_nominal(
    run_lock_update,  # type: RunLockUpdate
    lock,  # type: str
    path_mappings,  # type: PathMappings
):
    # type: (...) -> None

    lockfile = json_codec.load(lock, path_mappings)
    requirements = index_requirements(lockfile)
    proj_a_req = requirements.pop(ProjectName("proj-a"))
    requirements.pop(ProjectName("proj-b"))
    assert not requirements

    run_lock_update("-d", "proj-b").assert_success(
        expected_error_re=re_exact(
            dedent(
                """\
                Updates for lock generated by universal:
                  Deleted cowsay 6
                  Deleted proj-b 1
                Updates to lock input requirements:
                  Deleted 'proj-b==1.*'
                """
            )
        )
    )

    lockfile = json_codec.load(lock, path_mappings)
    requirements = index_requirements(lockfile)
    assert proj_a_req == requirements.pop(ProjectName("proj-a"))
    assert not requirements

    locked_requirements = locked_requirement_pins(lockfile)
    assert {
        pin("proj-a", "1.1"),
        pin("proj-c", "1"),
        pin("ansicolors", "1.1.8"),
    } == locked_requirements


def test_lock_update_delete_req_only(
    run_lock_update,  # type: RunLockUpdate
    lock,  # type: str
    path_mappings,  # type: PathMappings
):
    # type: (...) -> None

    lockfile = json_codec.load(lock, path_mappings)
    proj_a_req = index_requirements(lockfile)[ProjectName("proj-a")]
    original_locked_resolves = lockfile.locked_resolves

    run_lock_update("-d", "proj-a").assert_success(
        expected_error_re=re_exact(
            dedent(
                """\
                No updates for lock generated by universal.
                Updates to lock input requirements:
                  Deleted 'proj-a'
                """
            )
        )
    )
    lockfile = json_codec.load(lock, path_mappings)
    assert proj_a_req not in lockfile.requirements
    assert original_locked_resolves == lockfile.locked_resolves


def test_lock_update_delete_noop(
    run_lock_update,  # type: RunLockUpdate
    lock,  # type: str
    path_mappings,  # type: PathMappings
):
    # type: (...) -> None
    original_lockfile = json_codec.load(lock, path_mappings)
    run_lock_update("-d", "proj-c").assert_success(
        expected_error_re=re_exact("No updates for lock generated by universal.")
    )
    assert original_lockfile == json_codec.load(lock, path_mappings)


def test_lock_update_mixed(
    run_lock_update,  # type: RunLockUpdate
    lock,  # type: str
    path_mappings,  # type: PathMappings
):
    # type: (...) -> None

    run_lock_update("-p", "proj-a", "-d", "proj-b").assert_success(
        expected_error_re=re_exact(
            dedent(
                """\
                Updates for lock generated by universal:
                  Deleted cowsay 6
                  Deleted proj-b 1
                  Deleted proj-c 1
                  Updated proj-a from 1.1 to 2
                Updates to lock input requirements:
                  Deleted 'proj-b==1.*'
                """
            )
        )
    )
    lockfile = json_codec.load(lock, path_mappings)
    locked_requirements = locked_requirement_pins(lockfile)
    assert {pin("proj-a", "2"), pin("ansicolors", "1.1.8")} == locked_requirements


def test_lock_delete_complex(
    run_lock_update,  # type: RunLockUpdate
    lock,  # type: str
    path_mappings,  # type: PathMappings
):
    # type: (...) -> None

    run_lock_update("-d", "proj-b").assert_success(
        expected_error_re=re_exact(
            dedent(
                """\
                Updates for lock generated by universal:
                  Deleted cowsay 6
                  Deleted proj-b 1
                Updates to lock input requirements:
                  Deleted 'proj-b==1.*'
                """
            )
        )
    )
    lockfile = json_codec.load(lock, path_mappings)
    locked_requirements = locked_requirement_pins(lockfile)
    assert {
        pin("proj-a", "1.1"),
        pin("proj-c", "1"),
        pin("ansicolors", "1.1.8"),
    } == locked_requirements
