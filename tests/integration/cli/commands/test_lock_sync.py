# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import filecmp
import os.path
import re
import shutil
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.atomic_directory import atomic_directory
from pex.dist_metadata import find_distribution
from pex.pep_427 import InstallableType
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pip.version import PipVersion
from pex.resolve.locked_resolve import LockedResolve
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.path_mappings import PathMapping, PathMappings
from pex.resolve.resolved_requirement import Pin
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from testing import IntegResults, make_env, re_exact
from testing.cli import run_pex3
from testing.find_links import FindLinksRepo

if TYPE_CHECKING:
    from typing import Any, Iterable, List, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class SessionFixtures(object):
    find_links = attr.ib()  # type: str
    initial_lock = attr.ib()  # type: str


@pytest.fixture(scope="session")
def session_fixtures(shared_integration_test_tmpdir):
    # type: (str) -> SessionFixtures

    test_lock_sync_chroot = os.path.join(shared_integration_test_tmpdir, "test_lock_sync_chroot")
    with atomic_directory(test_lock_sync_chroot) as chroot:
        if not chroot.is_finalized():
            pip_version = PipVersion.DEFAULT
            find_links = os.path.join(chroot.work_dir, "find_links")
            find_links_repo = FindLinksRepo.create(find_links, pip_version)

            def host_requirements(*requirements):
                # type: (*str) -> None
                result = find_links_repo.resolver.resolve_requirements(
                    requirements,
                    result_type=InstallableType.WHEEL_FILE,
                )
                for resolved_distribution in result.distributions:
                    find_links_repo.host(resolved_distribution.distribution.location)

            # N.B.: Since we are setting up a find links repo for offline lock resolves, we grab one
            # distribution online to allow the current Pip version to bootstrap itself if needed.
            host_requirements(
                "cowsay==5.0.0",
                pip_version.setuptools_requirement,
                pip_version.wheel_requirement,
            )
            find_links_repo.make_wheel("foo", version="1")
            find_links_repo.make_wheel("bar", version="1")
            find_links_repo.make_wheel("baz", version="1")
            run_pex3(
                "lock",
                "create",
                "--path-mapping",
                "FL|{find_links}|Find Links Repo".format(find_links=find_links),
                "--no-pypi",
                "-f",
                find_links,
                "cowsay",
                "foo",
                "bar",
                "-o",
                os.path.join(chroot.work_dir, "lock.json"),
                "--indent",
                "2",
            ).assert_success()

            host_requirements("cowsay<6.1")
            find_links_repo.make_wheel("foo", version="2")
            find_links_repo.make_wheel("bar", version="2")
            find_links_repo.make_wheel("baz", version="2")

    return SessionFixtures(
        find_links=os.path.join(test_lock_sync_chroot, "find_links"),
        initial_lock=os.path.join(test_lock_sync_chroot, "lock.json"),
    )


@pytest.fixture(scope="session")
def find_links(session_fixtures):
    # type: (SessionFixtures) -> str
    return session_fixtures.find_links


@pytest.fixture(scope="session")
def path_mappings(find_links):
    # type: (str) -> PathMappings
    return PathMappings((PathMapping(path=find_links, name="FL"),))


@pytest.fixture
def initial_lock(
    tmpdir,  # type: str
    session_fixtures,  # type: SessionFixtures
):
    # type: (...) -> str
    initial_lock_copy = os.path.join(str(tmpdir), "lock.json")
    shutil.copy(session_fixtures.initial_lock, initial_lock_copy)
    return initial_lock_copy


@pytest.fixture
def repo_args(find_links):
    # type: (str) -> List[str]
    return ["--no-index", "-f", find_links]


@pytest.fixture
def path_mapping_args(path_mappings):
    # type: (PathMappings) -> List[str]
    args = []
    for path_mapping in path_mappings.mappings:
        args.append("--path-mapping")
        args.append(path_mapping.name + "|" + path_mapping.path)
    return args


NO_OUTPUT = r"^$"


def run_sync(
    *args,  # type: str
    **popen_kwargs  # type: Any
):
    # type: (...) -> IntegResults
    return run_pex3("lock", "sync", *args, **popen_kwargs)


def pin(
    project_name,  # type: str
    version,  # type: str
):
    # type: (...) -> Pin
    return Pin(ProjectName(project_name), Version(version))


def assert_lock(
    lock,  # type: Union[str, Lockfile]
    path_mappings,  # type: PathMappings
    expected_pins,  # type: Iterable[Pin]
):
    # type: (...) -> LockedResolve

    lock_file = (
        lock if isinstance(lock, Lockfile) else json_codec.load(lock, path_mappings=path_mappings)
    )
    assert len(lock_file.locked_resolves) == 1
    locked_resolve = lock_file.locked_resolves[0]
    assert sorted(expected_pins, key=str) == sorted(
        (locked_requirement.pin for locked_requirement in locked_resolve.locked_requirements),
        key=str,
    )
    return locked_resolve


def assert_venv(
    venv,  # type: Union[str, Virtualenv]
    expected_pins,  # type: Iterable[Pin]
):
    # type: (...) -> Virtualenv
    virtualenv = venv if isinstance(venv, Virtualenv) else Virtualenv(venv_dir=venv)
    assert sorted(expected_pins, key=str) == sorted(
        (
            Pin(distribution.metadata.project_name, distribution.metadata.version)
            for distribution in virtualenv.iter_distributions(rescan=True)
        ),
        key=str,
    )
    return virtualenv


def assert_lock_matches_venv(
    lock,  # type: str
    path_mappings,  # type: PathMappings
    venv,  # type: Union[str, Virtualenv]
    expected_pins,  # type: Iterable[Pin]
):
    # type: (...) -> Lockfile

    lock_file = json_codec.load(lock, path_mappings=path_mappings)
    assert_lock(lock_file, path_mappings, expected_pins)
    assert_venv(venv, expected_pins)
    return lock_file


def test_sync_implicit_create(
    tmpdir,  # type: Any
    repo_args,  # type: List[str]
    path_mappings,  # type: PathMappings
):
    # type: (...) -> None

    lock = os.path.join(str(tmpdir), "lock.json")
    run_sync("cowsay==5.0", "--lock", lock, *repo_args).assert_success()
    assert_lock(lock, path_mappings, expected_pins=[pin("cowsay", "5.0")])


def test_sync_implicit_create_lock_create_equivalence(
    tmpdir,  # type: Any
    repo_args,  # type: List[str]
    path_mappings,  # type: PathMappings
):
    # type: (...) -> None

    lock1 = os.path.join(str(tmpdir), "lock1.json")
    run_sync("cowsay==5.0", "--lock", lock1, *repo_args).assert_success()

    lock2 = os.path.join(str(tmpdir), "lock2.json")
    run_pex3("lock", "create", "cowsay==5.0", "-o", lock2, *repo_args).assert_success()
    assert filecmp.cmp(lock1, lock2, shallow=False)


def test_sync_implicit_create_venv(
    tmpdir,  # type: Any
    repo_args,  # type: List[str]
    path_mappings,  # type: PathMappings
):
    # type: (...) -> None

    lock = os.path.join(str(tmpdir), "lock.json")
    venv_dir = os.path.join(str(tmpdir), "venv")
    run_sync("cowsay==5.0", "--lock", lock, "--venv", venv_dir, *repo_args).assert_success()
    venv = Virtualenv(venv_dir)
    assert_lock_matches_venv(
        lock=lock, path_mappings=path_mappings, venv=venv, expected_pins=[pin("cowsay", "5.0")]
    )
    assert b"| Moo! |" in subprocess.check_output(args=[venv.bin_path("cowsay"), "Moo!"])


def test_sync_implicit_lock_create_venv_create_run(
    tmpdir,  # type: Any
    repo_args,  # type: List[str]
    path_mappings,  # type: PathMappings
):
    # type: (...) -> None

    lock = os.path.join(str(tmpdir), "lock.json")
    venv_dir = os.path.join(str(tmpdir), "venv")
    run_sync(
        *(repo_args + ["cowsay==5.0", "--lock", lock, "--venv", venv_dir, "--", "cowsay", "Moo!"])
    ).assert_success(expected_output_re=r".*| Moo! |.*", re_flags=re.DOTALL)
    assert_lock_matches_venv(
        lock=lock, path_mappings=path_mappings, venv=venv_dir, expected_pins=[pin("cowsay", "5.0")]
    )


def test_sync_noop(
    tmpdir,  # type: Any
    repo_args,  # type: List[str]
    initial_lock,  # type: str
    path_mappings,  # type: PathMappings
    path_mapping_args,  # type: List[str]
):
    # type: (...) -> None
    locked_resolve = assert_lock(
        initial_lock,
        path_mappings,
        expected_pins=[pin("cowsay", "5.0"), pin("foo", "1"), pin("bar", "1")],
    )
    result = run_sync(
        "cowsay", "foo", "bar", "--lock", initial_lock, *(repo_args + path_mapping_args)
    )
    result.assert_success(
        expected_output_re=NO_OUTPUT,
        expected_error_re=re_exact(
            "No updates for lock generated by {platform}.".format(
                platform=locked_resolve.platform_tag
            )
        ),
    )
    assert_lock(
        initial_lock,
        path_mappings,
        expected_pins=[pin("cowsay", "5.0"), pin("foo", "1"), pin("bar", "1")],
    )


def test_sync_update(
    tmpdir,  # type: Any
    repo_args,  # type: List[str]
    initial_lock,  # type: str
    path_mappings,  # type: PathMappings
    path_mapping_args,  # type: List[str]
):
    # type: (...) -> None
    locked_resolve = assert_lock(
        initial_lock,
        path_mappings,
        expected_pins=[pin("cowsay", "5.0"), pin("foo", "1"), pin("bar", "1")],
    )

    result = run_sync(
        "cowsay", "foo>1", "bar", "--lock", initial_lock, *(repo_args + path_mapping_args)
    )
    result.assert_success(
        expected_output_re=NO_OUTPUT,
        expected_error_re=re_exact(
            dedent(
                """\
                Updates for lock generated by {platform}:
                  Updated foo from 1 to 2
                Updates to lock input requirements:
                  Updated 'foo' to 'foo>1'
                """
            ).format(platform=locked_resolve.platform_tag)
        ),
    )
    assert_lock(
        initial_lock,
        path_mappings,
        expected_pins=[pin("cowsay", "5.0"), pin("foo", "2"), pin("bar", "1")],
    )


def test_sync_add(
    tmpdir,  # type: Any
    repo_args,  # type: List[str]
    initial_lock,  # type: str
    path_mappings,  # type: PathMappings
    path_mapping_args,  # type: List[str]
):
    # type: (...) -> None
    locked_resolve = assert_lock(
        initial_lock,
        path_mappings,
        expected_pins=[pin("cowsay", "5.0"), pin("foo", "1"), pin("bar", "1")],
    )

    result = run_sync(
        "cowsay", "foo", "bar", "baz", "--lock", initial_lock, *(repo_args + path_mapping_args)
    )
    result.assert_success(
        expected_output_re=NO_OUTPUT,
        expected_error_re=re_exact(
            dedent(
                """\
                Updates for lock generated by {platform}:
                  Added baz 2
                Updates to lock input requirements:
                  Added 'baz'
                """
            ).format(platform=locked_resolve.platform_tag)
        ),
    )
    assert_lock(
        initial_lock,
        path_mappings,
        expected_pins=[pin("cowsay", "5.0"), pin("foo", "1"), pin("bar", "1"), pin("baz", "2")],
    )


def test_sync_remove(
    tmpdir,  # type: Any
    repo_args,  # type: List[str]
    initial_lock,  # type: str
    path_mappings,  # type: PathMappings
    path_mapping_args,  # type: List[str]
):
    # type: (...) -> None
    locked_resolve = assert_lock(
        initial_lock,
        path_mappings,
        expected_pins=[pin("cowsay", "5.0"), pin("foo", "1"), pin("bar", "1")],
    )

    result = run_sync("cowsay", "foo", "--lock", initial_lock, *(repo_args + path_mapping_args))
    result.assert_success(
        expected_output_re=NO_OUTPUT,
        expected_error_re=re_exact(
            dedent(
                """\
                Updates for lock generated by {platform}:
                  Deleted bar 1
                Updates to lock input requirements:
                  Deleted 'bar'
                """
            ).format(platform=locked_resolve.platform_tag)
        ),
    )
    assert_lock(
        initial_lock,
        path_mappings,
        expected_pins=[pin("cowsay", "5.0"), pin("foo", "1")],
    )


def test_sync_complex(
    tmpdir,  # type: Any
    repo_args,  # type: List[str]
    initial_lock,  # type: str
    path_mappings,  # type: PathMappings
    path_mapping_args,  # type: List[str]
):
    # type: (...) -> None
    locked_resolve = assert_lock(
        initial_lock,
        path_mappings,
        expected_pins=[pin("cowsay", "5.0"), pin("foo", "1"), pin("bar", "1")],
    )

    # N.B.: Update foo, remove bar, add baz.
    result = run_sync(
        "cowsay", "foo<3", "baz<2", "--lock", initial_lock, *(repo_args + path_mapping_args)
    )
    result.assert_success(
        expected_output_re=NO_OUTPUT,
        expected_error_re=re_exact(
            dedent(
                """\
                Updates for lock generated by {platform}:
                  Deleted bar 1
                  Updated foo from 1 to 2
                  Added baz 1
                Updates to lock input requirements:
                  Deleted 'bar'
                  Updated 'foo' to 'foo<3'
                  Added 'baz<2'
                """
            ).format(platform=locked_resolve.platform_tag)
        ),
    )
    assert_lock(
        initial_lock,
        path_mappings,
        expected_pins=[pin("cowsay", "5.0"), pin("foo", "2"), pin("baz", "1")],
    )


@pytest.fixture
def initial_venv(
    tmpdir,  # type: Any
    repo_args,  # type: List[str]
    initial_lock,  # type: str
    path_mappings,  # type: PathMappings
    path_mapping_args,  # type: List[str]
):
    # type: (...) -> str
    venv_dir = os.path.join(str(tmpdir), "venv")
    run_pex3(
        "venv", "create", "-d", venv_dir, "--lock", initial_lock, *(repo_args + path_mapping_args)
    ).assert_success()
    assert_lock_matches_venv(
        lock=initial_lock,
        path_mappings=path_mappings,
        venv=venv_dir,
        expected_pins=[pin("cowsay", "5.0"), pin("foo", "1"), pin("bar", "1")],
    )
    return venv_dir


def test_sync_venv_noop(
    repo_args,  # type: List[str]
    initial_lock,  # type: str
    path_mappings,  # type: PathMappings
    path_mapping_args,  # type: List[str]
    initial_venv,  # type: str
):
    # type: (...) -> None

    # N.B.: There are no changed requirements and we don't pass "--yes", which would cause a
    # blocking input read if there needed to be any venv distribution deletes.
    run_sync(
        "cowsay",
        "foo",
        "bar",
        "--lock",
        initial_lock,
        "--venv",
        initial_venv,
        *(repo_args + path_mapping_args)
    ).assert_success()
    assert_lock_matches_venv(
        lock=initial_lock,
        path_mappings=path_mappings,
        venv=initial_venv,
        expected_pins=[pin("cowsay", "5.0"), pin("foo", "1"), pin("bar", "1")],
    )


def test_sync_venv_update(
    repo_args,  # type: List[str]
    initial_lock,  # type: str
    path_mappings,  # type: PathMappings
    path_mapping_args,  # type: List[str]
    initial_venv,  # type: str
):
    # type: (...) -> None

    # N.B.: The only changed requirement is "bar" -> "bar==2"
    run_sync(
        "--yes",
        "cowsay",
        "foo",
        "bar==2",
        "--lock",
        initial_lock,
        "--venv",
        initial_venv,
        *(repo_args + path_mapping_args)
    ).assert_success()
    assert_lock_matches_venv(
        lock=initial_lock,
        path_mappings=path_mappings,
        venv=initial_venv,
        expected_pins=[pin("cowsay", "5.0"), pin("foo", "1"), pin("bar", "2")],
    )


def test_sync_venv_add(
    repo_args,  # type: List[str]
    initial_lock,  # type: str
    path_mappings,  # type: PathMappings
    path_mapping_args,  # type: List[str]
    initial_venv,  # type: str
):
    # type: (...) -> None

    # N.B.: The only changed requirement is adding "baz" and we don't pass "--yes", which would be
    # required if there were venv dist deletes.
    run_sync(
        "cowsay",
        "foo",
        "bar",
        "baz",
        "--lock",
        initial_lock,
        "--venv",
        initial_venv,
        *(repo_args + path_mapping_args)
    ).assert_success()
    assert_lock_matches_venv(
        lock=initial_lock,
        path_mappings=path_mappings,
        venv=initial_venv,
        expected_pins=[pin("cowsay", "5.0"), pin("foo", "1"), pin("bar", "1"), pin("baz", "2")],
    )


def test_sync_venv_remove(
    repo_args,  # type: List[str]
    initial_lock,  # type: str
    path_mappings,  # type: PathMappings
    path_mapping_args,  # type: List[str]
    initial_venv,  # type: str
):
    # type: (...) -> None

    # N.B.: The only changed requirement is "cowsay" being removed.
    run_sync(
        "--yes",
        "foo",
        "bar",
        "--lock",
        initial_lock,
        "--venv",
        initial_venv,
        *(repo_args + path_mapping_args)
    ).assert_success()
    assert_lock_matches_venv(
        lock=initial_lock,
        path_mappings=path_mappings,
        venv=initial_venv,
        expected_pins=[pin("foo", "1"), pin("bar", "1")],
    )


def test_sync_venv_complex(
    repo_args,  # type: List[str]
    initial_lock,  # type: str
    path_mappings,  # type: PathMappings
    path_mapping_args,  # type: List[str]
    initial_venv,  # type: str
):
    # type: (...) -> None

    # N.B.: The "cowsay" and "foo" requirements are removed, "bar" -> "bar>1" and "baz" is added.
    run_sync(
        "--yes",
        "bar>1",
        "baz",
        "--lock",
        initial_lock,
        "--venv",
        initial_venv,
        *(repo_args + path_mapping_args)
    ).assert_success()
    assert_lock_matches_venv(
        lock=initial_lock,
        path_mappings=path_mappings,
        venv=initial_venv,
        expected_pins=[pin("bar", "2"), pin("baz", "2")],
    )


skip_cowsay6_for_python27 = pytest.mark.skipif(
    sys.version_info[0] < 3,
    reason=(
        "The cowsay 6.0 distribution is mistakenly resolvable by Python 2.7 (it does not have "
        "Requires-Python metadata), but it uses Python 3 syntax"
    ),
)


def assert_cowsay5(venv):
    # type: (Virtualenv) -> None
    assert b"| Moo! |" in subprocess.check_output(args=[venv.bin_path("cowsay"), "Moo!"])


@skip_cowsay6_for_python27
def test_sync_venv_run(
    tmpdir,  # type: Any
    repo_args,  # type: List[str]
    path_mappings,  # type: PathMappings
):
    # type: (...) -> None

    # N.B.: The cowsay 5.0 -> cowsay 6.0 transition is picked, in part, because cowsay 5.0 is sdist
    # only on PyPI. Older versions of Pip (those that come with the venvs created by Python 3.10
    # and older), install sdists as `.egg-info` distributions in site-packages instead of
    # regularizing to `.dist-info` as is done in newer versions of Pip. In that way our CI test
    # matrix ensures we test both `.dist-info` and `.egg-info` distributions are properly detected
    # and removed when appropriate.

    lock = os.path.join(str(tmpdir), "lock.json")
    run_pex3("lock", "create", "cowsay==5.0", "-o", lock, *repo_args).assert_success()
    # N.B.: There is no Pip in the lock.
    assert_lock(lock, path_mappings, expected_pins=[pin("cowsay", "5.0")])

    venv_dir = os.path.join(str(tmpdir), "venv")
    run_pex3("venv", "create", "-d", venv_dir, "--lock", lock, "--pip", *repo_args).assert_success()
    venv = Virtualenv(venv_dir)
    assert (
        any(ProjectName("pip") == dist.metadata.project_name for dist in venv.iter_distributions())
        > 0
    ), "We expect the initial venv to include Pip."
    assert_cowsay5(venv)

    result = run_sync(
        *(
            repo_args
            + [
                "--yes",
                "cowsay<6.1",
                "--lock",
                lock,
                "--",
                venv.bin_path("cowsay"),
                "-t",
                "A New Moo!",
            ]
        )
    )
    result.assert_success(expected_output_re=r".*| A New Moo! |.*", re_flags=re.DOTALL)

    # N.B.: Since the venv now matches the lock, this means Pip and its dist dependencies were
    # nuked, confirming the default --no-retain-pip mode.
    lockfile = assert_lock_matches_venv(
        lock=lock, path_mappings=path_mappings, venv=venv_dir, expected_pins=[pin("cowsay", "6.0")]
    )
    assert (
        dedent(
            """\
            Updates for lock generated by {platform}:
              Updated cowsay from 5 to 6
            Updates to lock input requirements:
              Updated 'cowsay==5.0' to 'cowsay<6.1'
            """
        ).format(platform=lockfile.locked_resolves[0].platform_tag)
        == result.error
    )


def test_sync_venv_dry_run(
    tmpdir,  # type: Any
    repo_args,  # type: List[str]
    path_mappings,  # type: PathMappings
):
    # type: (...) -> None

    lock = os.path.join(str(tmpdir), "lock.json")
    run_pex3("lock", "create", "cowsay==5.0", "-o", lock, *repo_args).assert_success()
    locked_resolve = assert_lock(lock, path_mappings, expected_pins=[pin("cowsay", "5.0")])

    venv_dir = os.path.join(str(tmpdir), "venv")
    run_pex3("venv", "create", "-d", venv_dir, "--lock", lock, "--pip", *repo_args).assert_success()
    venv = Virtualenv(venv_dir)
    assert_cowsay5(venv)

    run_sync(
        *(
            repo_args
            + [
                "cowsay<6.1",
                "--lock",
                lock,
                "--dry-run",
                "--",
                "cowsay",
                "-t",
                "I would have mooed!",
            ]
        ),
        # Simulate an activated venv with its bin dir inserted n the PATH.
        env=make_env(
            PATH=os.pathsep.join(
                [venv.bin_dir] + os.environ.get("PATH", os.defpath).split(os.pathsep)
            )
        )
    ).assert_success(
        expected_output_re=re_exact(
            dedent(
                """\
                Updates for lock generated by {platform}:
                  Would update cowsay from 5 to 6
                Updates to lock input requirements:
                  Would update 'cowsay==5.0' to 'cowsay<6.1'
                Would sync venv at {venv_dir} and run the following command in it:
                  {cowsay} -t 'I would have mooed!'
                """
            ).format(
                platform=locked_resolve.platform_tag,
                venv_dir=venv_dir,
                cowsay=venv.bin_path("cowsay"),
            )
        ),
        expected_error_re=NO_OUTPUT,
    )


@skip_cowsay6_for_python27
def test_sync_venv_run_retain_pip(
    tmpdir,  # type: Any
    repo_args,  # type: List[str]
    path_mappings,  # type: PathMappings
):
    # type: (...) -> None

    venv_dir = os.path.join(str(tmpdir), "venv")
    venv = Virtualenv.create(venv_dir)
    venv.install_pip()
    pip = find_distribution("pip", search_path=venv.sys_path)
    assert pip is not None
    pip_pin = pin("pip", pip.version)

    subprocess.check_call(args=[venv.bin_path("pip"), "install", "cowsay==5.0"] + repo_args)
    assert_cowsay5(venv)

    lock = os.path.join(str(tmpdir), "lock.json")
    result = run_sync(
        *(
            repo_args
            + [
                "--retain-pip",
                "--yes",
                "cowsay<6.1",
                "--lock",
                lock,
                "--",
                venv.bin_path("cowsay"),
                "-t",
                "A New Moo!",
            ]
        )
    )
    result.assert_success(expected_output_re=r".*| A New Moo! |.*", re_flags=re.DOTALL)
    assert not result.error

    assert_lock(lock, path_mappings, expected_pins=[pin("cowsay", "6.0")])
    assert_venv(venv_dir, expected_pins=[pin("cowsay", "6.0"), pip_pin])

    # And check Pip still works.
    subprocess.check_call(args=[venv.bin_path("pip"), "uninstall", "--yes", "cowsay"])
    assert_venv(venv_dir, expected_pins=[pip_pin])
    subprocess.check_call(args=[venv.bin_path("pip"), "install", "cowsay==5.0"] + repo_args)
    assert_venv(venv_dir, expected_pins=[pin("cowsay", "5.0"), pip_pin])
    assert_cowsay5(venv)
