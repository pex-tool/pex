# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
from textwrap import dedent

import colors  # vendor:skip
import pytest

from pex import dist_metadata
from pex.common import open_zip, safe_open
from pex.dist_metadata import ProjectNameAndVersion
from pex.interpreter import PythonInterpreter
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper
from testing import IS_PYPY, PY_VER, built_wheel, make_env, run_pex_command
from testing.cli import run_pex3
from testing.lock import index_lock_artifacts
from testing.pytest.tmp import Tempdir, TempdirFactory

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


@pytest.fixture(scope="module")
def requests_lock_strict(
    tmpdir_factory,  # type: TempdirFactory
    request,  # type: Any
):
    # type: (...) -> str

    lock = tmpdir_factory.mktemp("locks", request=request).join("requests.lock")
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
    tmpdir_factory,  # type: TempdirFactory
    request,  # type: Any
    requests_lock_strict,  # type: str
):
    # type: (...) -> str

    requests_pex = tmpdir_factory.mktemp("tool", request=request).join("requests.pex")
    run_pex_command(
        args=["--lock", requests_lock_strict, "--include-tools", "requests", "-o", requests_pex]
    ).assert_success()
    return requests_pex


@pytest.fixture
def requests_lock_findlinks(
    tmpdir_factory,  # type: TempdirFactory
    request,  # type: Any
    requests_tool_pex,  # type: str
):
    # type: (...) -> LockAndRepo

    find_links_repo = str(tmpdir_factory.mktemp("repo", request=request))
    subprocess.check_call(
        args=[requests_tool_pex, "repository", "extract", "-f", find_links_repo],
        env=make_env(PEX_TOOLS=1),
    )
    lock = tmpdir_factory.mktemp("locks", request=request).join("requests-find-links.lock")
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
        r"    .* No such file or directory: .*'{requests_distribution}'".format(
            requests_distribution=re.escape(requests_distribution)
        ),
        result.error,
        re.MULTILINE,
    )


def test_multiplatform(
    tmpdir,  # type: Tempdir
    py38,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    requests_lock_universal = tmpdir.join("requests-universal.lock")
    run_pex3(
        "lock",
        "create",
        "--resolver-version",
        "pip-2020-resolver",
        "--style",
        "universal",
        "--interpreter-constraint",
        # N.B.: Ensure the lock covers 3.8 and 3.10, which we use below to build a multiplatform
        # PEX.
        ">=3.8,!=3.9.*,<3.11",
        "requests[security]==2.25.1",
        "-o",
        requests_lock_universal,
    ).assert_success()

    pex_file = tmpdir.join("pex.file")
    run_pex_command(
        args=[
            "--python",
            py38.binary,
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
    py38.execute(check_command)
    py310.execute(check_command)


def test_issue_1413_portable_find_links(tmpdir):
    # type: (Any) -> None

    # Set up a lockfile with contents both from PyPI and a local find-links repo that uses
    # --path-mapping for lock file portability.
    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "app.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import colors
                
                
                print(colors.blue("Relocatable!"))
                """
            )
        )

    repository_pex = os.path.join(str(tmpdir), "myappnotonpypi.pex")
    run_pex_command(
        args=["-D", src, "ansicolors==1.1.8", "-m", "app", "--include-tools", "-o", repository_pex]
    ).assert_success()
    assert (
        colors.blue("Relocatable!")
        == subprocess.check_output(args=[repository_pex]).decode("utf-8").strip()
    )

    original_find_links = os.path.join(str(tmpdir), "find-links", "original")
    subprocess.check_call(
        args=[repository_pex, "repository", "extract", "--sources", "-f", original_find_links],
        env=make_env(PEX_TOOLS=1),
    )

    # We should have only the sdist of the src/app.py source code available in the find-links repo.
    os.unlink(os.path.join(original_find_links, "ansicolors-1.1.8-py2.py3-none-any.whl"))
    assert 1 == len(os.listdir(original_find_links))
    assert 1 == len(glob.glob(os.path.join(original_find_links, "myappnotonpypi-0.0.0*.tar.gz")))

    lock = os.path.join(str(tmpdir), "lock")
    run_pex3(
        "lock",
        "create",
        "ansicolors==1.1.8",
        "myappnotonpypi",
        "-f",
        original_find_links,
        "--path-mapping",
        "FOO|{path}|Our local neighborhood find-links repo.".format(path=original_find_links),
        "-o",
        lock,
    ).assert_success()

    # Now simulate using the portable lock file on another machine where the find-links repo is
    # mounted at a different absolute path than it was when creating the lock.
    moved_find_links = os.path.join(str(tmpdir), "find-links", "moved")
    os.rename(original_find_links, moved_find_links)
    assert not os.path.exists(original_find_links)

    result = run_pex_command(
        args=["--lock", lock, "--path-mapping", "FOO|{path}".format(path=moved_find_links), "-mapp"]
    )
    result.assert_success()
    assert colors.blue("Relocatable!") == result.output.strip()


def test_issue_1717_transitive_extras(
    tmpdir,  # type: Any
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    find_links = os.path.join(str(tmpdir), "find-links")
    # The dep graph where a naive depth first resolve not accounting for extras would grab:
    #   [root, middle_man_with_extras, A, B, C]
    # Instead of the expected:
    #   [root, middle_man_with_extras, A, extra1, B, extra2, C]
    #
    # root ->
    #     middle_man_with_extras
    #     A ->
    #         middle_man_with_extras[E1] ->
    #             extra1
    #         B ->
    #             middle_man_with_extras[E1,E2] ->
    #                 extra1
    #                 extra2
    #             C ->
    #                 middle_man_with_extras[E2] ->
    #                     extra2

    with built_wheel(
        name="root",
        install_reqs=["middle_man_with_extras", "A"],
    ) as root, built_wheel(
        name="A",
        install_reqs=["middle_man_with_extras[E1]", "B"],
    ) as A, built_wheel(
        name="B",
        install_reqs=["middle_man_with_extras[E1,E2]", "C"],
    ) as B, built_wheel(
        name="C",
        install_reqs=["middle_man_with_extras[E2]"],
    ) as C, built_wheel(
        name="middle_man_with_extras",
        extras_require={"E1": ["extra1"], "E2": ["extra2"]},
    ) as middle_man_with_extras, built_wheel(
        name="extra1",
    ) as extra1, built_wheel(
        name="extra2",
    ) as extra2:
        os.mkdir(find_links)
        for wheel in root, A, B, C, middle_man_with_extras, extra1, extra2:
            shutil.move(wheel, find_links)

    lock = os.path.join(str(tmpdir), "lock")
    run_pex3(
        "lock",
        "create",
        "--resolver-version",
        "pip-2020-resolver",
        "--no-pypi",
        "-f",
        find_links,
        "root",
        "-o",
        lock,
    ).assert_success()

    pex = os.path.join(str(tmpdir), "pex")
    pex_root = os.path.join(str(tmpdir), "pex_root")
    create_pex_args = [
        "--lock",
        lock,
        "-o",
        pex,
        "--pex-root",
        pex_root,
        "--runtime-pex-root",
        pex_root,
    ]
    test_pex_args = [pex, "-c", "import root"]

    def assert_requirements(pex_info):
        # type: (PexInfo) -> None
        assert ["root"] == list(pex_info.requirements)

    def assert_dists(
        pex_info,  # type: PexInfo
        *expected_project_names  # type: str
    ):
        # type: (...) -> None
        assert set(expected_project_names) == {
            ProjectNameAndVersion.from_filename(d).project_name for d in pex_info.distributions
        }

    # N.B.: Pex 2.1.78 only works on CPython 3.10 and older and PyPy 3.7 and older.
    python = py310.binary if PY_VER > (3, 10) or (IS_PYPY and PY_VER > (3, 7)) else sys.executable
    run_pex_command(
        args=["pex==2.1.78", "-cpex", "--"] + create_pex_args, python=python
    ).assert_success()
    pex_info = PexInfo.from_pex(pex)
    assert_requirements(pex_info)
    assert_dists(pex_info, "root", "middle_man_with_extras", "A", "B", "C")

    process = subprocess.Popen(args=[python] + test_pex_args, stderr=subprocess.PIPE)
    _, stderr = process.communicate()
    assert 0 != process.returncode

    assert (
        re.search(
            r"ResolveError: Failed to resolve requirements from PEX environment @ {pex_root}.*\n"
            # Interpreter platform string wildcarded:
            r"Needed [a-z0-9_-]+ compatible dependencies for:\n"
            r' 1: extra1; extra == "e1"\n'
            r"    Required by:\n"
            r"      FingerprintedDistribution\(distribution=middle-man-with-extras .*\)\n"
            # Python 2 unicode literal wildcarded:
            r"    But this pex had no u?'extra1' distributions.\n"
            r' 2: extra2; extra == "e2"\n'
            r"    Required by:\n"
            r"      FingerprintedDistribution\(distribution=middle-man-with-extras .*\)\n"
            # Python 2 unicode literal wildcarded:
            r"    But this pex had no u?'extra2' distributions.\n".format(
                pex_root=re.escape(pex_root)
            ),
            stderr.decode("utf-8"),
        )
        is not None
    ), stderr.decode("utf-8")

    run_pex_command(args=create_pex_args).assert_success()
    pex_info = PexInfo.from_pex(pex)
    assert_requirements(pex_info)
    assert_dists(pex_info, "root", "middle_man_with_extras", "A", "extra1", "B", "extra2", "C")
    subprocess.check_call(args=test_pex_args)


def test_resolve_wheel_files(tmpdir):
    # type: (Any) -> None

    lock = os.path.join(str(tmpdir), "lock")
    # N.B.: We choose ansicolors 1.1.8 since it works with all Pythons and has a universal wheel
    # published on PyPI and cowsay 5.0 since it also works with all Pythons and only has an sdist
    # published on PyPI. This combination ensures the resolve process can handle both building
    # wheels (cowsay stresses this) and using pre-existing ones (ansicolors stresses this).
    run_pex3("lock", "create", "ansicolors==1.1.8", "cowsay==5.0", "-o", lock).assert_success()

    pex = os.path.join(str(tmpdir), "pex")
    exe = os.path.join(str(tmpdir), "exe")
    with open(exe, "w") as fp:
        fp.write("import colors, cowsay; cowsay.tux(colors.blue('Moo?'))")

    run_pex_command(
        args=["--lock", lock, "--no-pre-install-wheels", "-o", pex, "--exe", exe]
    ).assert_success()

    assert colors.blue("Moo?") in subprocess.check_output(args=[pex]).decode("utf-8")

    pex_info = PexInfo.from_pex(pex)
    assert frozenset(
        (ProjectNameAndVersion("ansicolors", "1.1.8"), ProjectNameAndVersion("cowsay", "5.0"))
    ) == frozenset(ProjectNameAndVersion.from_filename(dist) for dist in pex_info.distributions)

    dist_dir = os.path.join(str(tmpdir), "dist_dir")
    os.mkdir(dist_dir)
    with open_zip(pex) as zfp:
        for location, sha in pex_info.distributions.items():
            dist_relpath = os.path.join(pex_info.internal_cache, location)
            zfp.extract(dist_relpath, dist_dir)
            assert sha == CacheHelper.hash(
                os.path.join(dist_dir, dist_relpath), hasher=hashlib.sha256
            )
