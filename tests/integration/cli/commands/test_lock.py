# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import os
import re
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.cli.testing import run_pex3
from pex.interpreter import PythonInterpreter
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve import lockfile
from pex.resolve.locked_resolve import Artifact, LockedRequirement
from pex.resolve.lockfile import Lockfile
from pex.resolve.lockfile.download_manager import DownloadedArtifact
from pex.resolve.resolved_requirement import Fingerprint, Pin
from pex.resolve.resolver_configuration import ResolverVersion
from pex.resolve.testing import normalize_locked_resolve
from pex.sorted_tuple import SortedTuple
from pex.targets import LocalInterpreter
from pex.testing import (
    IS_MAC,
    IS_PYPY,
    PY310,
    PY_VER,
    IntegResults,
    ensure_python_interpreter,
    make_env,
    run_pex_command,
)
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper
from pex.version import __version__

if TYPE_CHECKING:
    from typing import Any, Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def normalize_lockfile(
    lockfile,  # type: Lockfile
    skip_additional_artifacts=False,  # type: bool
    skip_urls=False,  # type: bool
):
    # type: (...) -> Lockfile
    return attr.evolve(
        lockfile,
        locked_resolves=SortedTuple(
            normalize_locked_resolve(
                locked_resolve,
                skip_additional_artifacts=skip_additional_artifacts,
                skip_urls=skip_urls,
            )
            for locked_resolve in lockfile.locked_resolves
        ),
        requirements=SortedTuple(),
    )


def test_create(tmpdir):
    # type: (Any) -> None

    lock_file = os.path.join(str(tmpdir), "requirements.lock.json")
    run_pex3("lock", "create", "ansicolors", "-o", lock_file).assert_success()

    requirements_file = os.path.join(str(tmpdir), "requirements.lock.txt")
    run_pex3("lock", "export", "-o", requirements_file, lock_file).assert_success()

    # We should get back the same lock given a lock as input mod comments (in particular the via
    # comment line which is sensitive to the source of the requirements)
    result = run_pex3("lock", "create", "-r", requirements_file)
    result.assert_success()
    assert normalize_lockfile(lockfile.load(lock_file)) == normalize_lockfile(
        lockfile.loads(result.output)
    )


def test_create_style(tmpdir):
    # type: (Any) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")

    def create_lock(
        style,  # type: str
        interpreter_constraint=None,  # type: Optional[str]
    ):
        # type: (...) -> LockedRequirement
        lock_file = os.path.join(str(tmpdir), "{}.lock".format(style))
        args = [
            "lock",
            "create",
            "psutil==5.9.0",
            "-o",
            lock_file,
            "--style",
            style,
            "--pex-root",
            pex_root,
        ]
        if interpreter_constraint:
            args.extend(["--interpreter-constraint", interpreter_constraint])
        run_pex3(*args).assert_success()
        lock = lockfile.load(lock_file)
        assert 1 == len(lock.locked_resolves)
        locked_resolve = lock.locked_resolves[0]
        assert 1 == len(locked_resolve.locked_requirements)
        locked_requirement = locked_resolve.locked_requirements[0]
        download_dir = os.path.join(
            pex_root, "downloads", locked_requirement.artifact.fingerprint.hash
        )
        downloaded_artifact = DownloadedArtifact.load(download_dir)
        assert os.path.exists(downloaded_artifact.path), (
            "Expected the primary artifact to be downloaded as a side-effect of executing the lock "
            "resolve."
        )
        assert (
            CacheHelper.hash(
                downloaded_artifact.path, digest=downloaded_artifact.fingerprint.new_hasher()
            )
            == downloaded_artifact.fingerprint
        ), (
            "Expected the primary artifact to have an internal fingerprint established to short "
            "circuit builds and installs."
        )
        return locked_requirement

    # See: https://pypi.org/project/psutil/5.9.0/#files

    assert not create_lock("strict").additional_artifacts

    # We should have 2 total artifacts for a sources lock for most interpreters since we know
    # psutil 5.9.0 provides an sdist and wheels for CPython 2.7 (but not for macOS) and CPython 3.6
    # through 3.10.
    python_identity = PythonInterpreter.get().identity
    expected_additional = (
        1
        if not IS_PYPY
        and ((PY_VER == (2, 7) and not IS_MAC) or python_identity.matches("CPython>=3.6,<3.11"))
        else 0
    )
    assert expected_additional == len(create_lock("sources").additional_artifacts)

    # We should have 32 total artifacts for a universal lock since we know psutil 5.9.0 provides
    # an sdist and 31 wheels.
    assert 31 == len(create_lock("universal").additional_artifacts)

    # We should have 6 total artifacts for a constrained universal lock since we know psutil 5.9.0
    # provides an sdist and 5 Python 3.10 wheels.
    assert 5 == len(create_lock("universal", interpreter_constraint="~=3.10").additional_artifacts)


def test_create_local_unsupported(pex_project_dir):
    # type: (str) -> None

    result = run_pex3("lock", "create", pex_project_dir)
    result.assert_failure()
    assert (
        "Cannot create a lock for project requirements built from local sources. Given 1 such "
        "project:\n"
        "1.) local project at {path}\n".format(path=pex_project_dir)
    ) == result.error


def test_create_vcs(tmpdir):
    # type: (Any) -> None

    lock = os.path.join(str(tmpdir), "lock")
    run_pex3(
        "lock",
        "create",
        "pex @ git+https://github.com/pantsbuild/pex@473c6ac7",
        "git+https://github.com/VaasuDevanS/cowsay-python@v3.0#egg=cowsay",
        "-o",
        lock,
    ).assert_success()
    pex_file = os.path.join(str(tmpdir), "pip-pex.pex")
    run_pex_command(args=["--lock", lock, "-o", pex_file]).assert_success()

    assert (
        "3.0"
        == subprocess.check_output(args=[pex_file, "--version"], env=make_env(PEX_SCRIPT="cowsay"))
        .decode("utf-8")
        .strip()
    )

    process = subprocess.Popen(
        args=[pex_file, "-V"],
        env=make_env(PEX_SCRIPT="pex"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate()
    assert 0 == process.returncode

    # The argparse system emits version to stderr under Python 2.7.
    output = stderr if sys.version_info[0] == 2 else stdout
    assert "2.1.61" == output.decode("utf-8").strip()


def test_create_universal_python_unsupported():
    # type: () -> None

    result = run_pex3(
        "lock", "create", "--style", "universal", "--python", "python3.10", "ansicolors"
    )
    result.assert_failure()
    assert (
        "When creating a universal lock, the interpreters the resulting lock applies to can only "
        "be constrained via --interpreter-constraint. There was 1 --python and 0 --platform "
        "specified.\n"
    ) == result.error


def test_create_universal_platform_unsupported():
    # type: () -> None

    result = run_pex3(
        "lock",
        "create",
        "--style",
        "universal",
        "--platform",
        "linux_x86_64-cp-310-cp310.",
        "ansicolors",
    )
    result.assert_failure()
    assert (
        "When creating a universal lock, the interpreters the resulting lock applies to can only "
        "be constrained via --interpreter-constraint. There was 0 --python and 1 --platform "
        "specified.\n"
    ) == result.error


UPDATE_LOCKFILE_CONTENTS = """\
{
  "allow_builds": true,
  "allow_prereleases": false,
  "allow_wheels": true,
  "build_isolation": true,
  "constraints": [],
  "locked_resolves": [
    {
      "locked_requirements": [
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "50b1e4f8446b06f41be7dd6338db18e0990601dce795c2b1686458aa7e8fa7d8",
              "url": "https://files.pythonhosted.org/packages/05/1b/0a0dece0e8aa492a6ec9e4ad2fe366b511558cdc73fd3abc82ba7348e875/certifi-2021.5.30-py2.py3-none-any.whl"
            }
          ],
          "project_name": "certifi",
          "requires_dists": [],
          "requires_python": null,
          "version": "2021.5.30"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "5d209c0a931f215cee683b6445e2d77677e7e75e159f78def0db09d68fafcaa6",
              "url": "https://files.pythonhosted.org/packages/3f/65/69e6754102dcd018a0f29e4db673372eb323ee504431125ab6c9109cb21c/charset_normalizer-2.0.6-py3-none-any.whl"
            }
          ],
          "project_name": "charset-normalizer",
          "requires_dists": [
            "unicodedata2; extra == \\"unicode_backport\\""
          ],
          "requires_python": ">=3.5.0",
          "version": "2.0.6"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "14475042e284991034cb48e06f6851428fb14c4dc953acd9be9a5e95c7b6dd7a",
              "url": "https://files.pythonhosted.org/packages/d7/77/ff688d1504cdc4db2a938e2b7b9adee5dd52e34efbd2431051efc9984de9/idna-3.2-py3-none-any.whl"
            }
          ],
          "project_name": "idna",
          "requires_dists": [],
          "requires_python": ">=3.5",
          "version": "3.2"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "6c1246513ecd5ecd4528a0906f910e8f0f9c6b8ec72030dc9fd154dc1a6efd24",
              "url": "https://files.pythonhosted.org/packages/92/96/144f70b972a9c0eabbd4391ef93ccd49d0f2747f4f6a2a2738e99e5adc65/requests-2.26.0-py2.py3-none-any.whl"
            }
          ],
          "project_name": "requests",
          "requires_dists": [
            "PySocks!=1.5.7,>=1.5.6; extra == \\"socks\\"",
            "certifi>=2017.4.17",
            "chardet<5,>=3.0.2; extra == \\"use_chardet_on_py3\\"",
            "chardet<5,>=3.0.2; python_version < \\"3\\"",
            "charset-normalizer~=2.0.0; python_version >= \\"3\\"",
            "idna<3,>=2.5; python_version < \\"3\\"",
            "idna<4,>=2.5; python_version >= \\"3\\"",
            "urllib3<1.27,>=1.21.1",
            "win-inet-pton; (sys_platform == \\"win32\\" and python_version == \\"2.7\\") and extra == \\"socks\\""
          ],
          "requires_python": "!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*,!=3.5.*,>=2.7",
          "version": "2.26"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "f5321fbe4bf3fefa0efd0bfe7fb14e90909eb62a48ccda331726b4319897dd5e",
              "url": "https://files.pythonhosted.org/packages/56/aa/4ef5aa67a9a62505db124a5cb5262332d1d4153462eb8fd89c9fa41e5d92/urllib3-1.25.11-py2.py3-none-any.whl"
            }
          ],
          "project_name": "urllib3",
          "requires_dists": [],
          "requires_python": null,
          "version": "1.25.11"
        }
      ],
      "platform_tag": [
        "cp38",
        "cp38",
        "manylinux_2_33_x86_64"
      ]
    }
  ],
  "pex_version": "2.1.50",
  "prefer_older_binary": false,
  "requirements": [
    "requests"
  ],
  "requires_python": [],
  "resolver_version": "pip-2020-resolver",
  "style": "strict",
  "transitive": true,
  "use_pep517": null
}
"""


UPDATE_LOCKFILE = lockfile.loads(UPDATE_LOCKFILE_CONTENTS)


def write_lock_file(
    tmpdir,  # type: Any
    contents,  # type: str
):
    # type: (...) -> str
    lock_file = os.path.join(str(tmpdir), "lock.json")
    with open(lock_file, "w") as fp:
        fp.write(contents)
    return lock_file


@pytest.fixture
def lock_file_path(tmpdir):
    # type: (Any) -> str
    return write_lock_file(tmpdir, UPDATE_LOCKFILE_CONTENTS)


def run_lock_update(
    *args,  # type: str
    **popen_kwargs  # type: Any
):
    # type: (...) -> IntegResults
    return run_pex3("lock", "update", *args, **popen_kwargs)


def ensure_py310():
    # type: () -> str
    return ensure_python_interpreter(PY310)


@pytest.fixture
def py310():
    # type: () -> str
    return ensure_py310()


def run_lock_update_for_py310(
    *args,  # type: str
    **popen_kwargs  # type: Any
):
    # type: (...) -> IntegResults
    py38 = ensure_py310()
    return run_lock_update("--python", py38, *args, **popen_kwargs)


def test_update_noop(lock_file_path):
    # type: (str) -> None
    result = run_lock_update_for_py310("-p", "urllib3==1.25.11", lock_file_path)
    result.assert_success()
    assert not result.output
    assert (
        "There were no updates for urllib3 in lock generated by cp38-cp38-manylinux_2_33_x86_64.\n"
        == result.error
    )
    assert UPDATE_LOCKFILE == lockfile.load(lock_file_path)


def test_update_noop_dry_run(lock_file_path):
    # type: (str) -> None
    result = run_lock_update_for_py310("-n", "-p", "urllib3==1.25.11", lock_file_path)
    result.assert_success()
    assert (
        "There would be no updates for urllib3 in lock generated by "
        "cp38-cp38-manylinux_2_33_x86_64.\n" == result.output
    )
    assert not result.error


def test_update_targeted_upgrade_miss(lock_file_path):
    # type: (str) -> None
    result = run_lock_update_for_py310("-p", "not_in_lock==1.0", lock_file_path)
    result.assert_failure()
    assert not result.output
    assert (
        "The following updates were requested but there were no matching locked requirements "
        "found in {lock_file}:\n"
        "+ not_in_lock==1.0\n".format(lock_file=lock_file_path)
    ) == result.error


def test_update_targeted_upgrade(lock_file_path):
    # type: (str) -> None
    assert SortedTuple() == lockfile.load(lock_file_path).constraints
    result = run_lock_update_for_py310("-p", "urllib3<1.26.7", lock_file_path)
    result.assert_success()
    assert not result.output
    assert (
        "Updated urllib3 from 1.25.11 to 1.26.6 in lock generated by "
        "cp38-cp38-manylinux_2_33_x86_64.\n" == result.error
    )

    lock_file = lockfile.load(lock_file_path)
    assert SortedTuple([Requirement.parse("urllib3<1.26.7")]) == lock_file.constraints
    assert 1 == len(lock_file.locked_resolves)
    locked_resolve = lock_file.locked_resolves[0]
    assert 5 == len(locked_resolve.locked_requirements)
    for index, locked_requirement in enumerate(locked_resolve.locked_requirements):
        if ProjectName("urllib3") == locked_requirement.pin.project_name:
            assert (
                UPDATE_LOCKFILE.locked_resolves[0].locked_requirements[index] != locked_requirement
            )
            assert Version("1.26.6") == locked_requirement.pin.version
        else:
            assert (
                UPDATE_LOCKFILE.locked_resolves[0].locked_requirements[index] == locked_requirement
            )


def test_update_targeted_upgrade_dry_run(lock_file_path):
    # type: (str) -> None
    result = run_lock_update_for_py310("-n", "-p", "urllib3<1.26.7", lock_file_path)
    result.assert_success()
    assert (
        "Would update urllib3 from 1.25.11 to 1.26.6 in lock generated by "
        "cp38-cp38-manylinux_2_33_x86_64.\n" == result.output
    )
    assert not result.error
    assert UPDATE_LOCKFILE == lockfile.load(
        lock_file_path
    ), "A dry run update should not have updated the lock file."


def test_update_targeted_downgrade(lock_file_path):
    # type: (str) -> None
    result = run_lock_update_for_py310("-p", "urllib3<1.25", lock_file_path)
    result.assert_success()
    assert not result.output
    assert (
        "Updated urllib3 from 1.25.11 to 1.24.3 in lock generated by "
        "cp38-cp38-manylinux_2_33_x86_64.\n" == result.error
    )


def test_update_targeted_closure_shrink(lock_file_path):
    # type: (str) -> None

    # Older requests distributions were self-contained universal wheels with vendored dependencies.
    # A targeted downgrade of requests, then, should remove newer requests dependencies from the
    # lock.

    result = run_lock_update_for_py310("-p", "requests==2.0.0", lock_file_path)
    result.assert_success()
    lock_file = lockfile.load(lock_file_path)
    assert 1 == len(lock_file.locked_resolves)
    locked_resolve = lock_file.locked_resolves[0]
    assert [
        LockedRequirement.create(
            pin=Pin(
                project_name=ProjectName(project_name=u"requests"), version=Version(version="2")
            ),
            artifact=Artifact.from_url(
                url="https://files.pythonhosted.org/packages/bf/78/be2b4c440ea767336d8448fe671fe1d78ca499e49d77dac90f92191cca0e/requests-2.0.0-py2.py3-none-any.whl",
                fingerprint=Fingerprint(
                    algorithm="sha256",
                    hash="2ef65639cb9600443f85451df487818c31f993ab288f313d29cc9db4f3cbe6ed",
                ),
            ),
        )
    ] == list(locked_resolve.locked_requirements)


def test_update_targeted_impossible(
    lock_file_path,  # type: str
    tmpdir,  # type: Any
    py310,
):
    # type: (...) -> None
    result = run_lock_update_for_py310("-p", "urllib3<1.16", lock_file_path)
    result.assert_failure()
    assert not result.output

    error_lines = result.error.splitlines()
    assert [
        "ERROR: Could not find a version that satisfies the requirement urllib3<1.27,>=1.21.1 "
        "(from requests)",
        "ERROR: No matching distribution found for urllib3<1.27,>=1.21.1",
        "ERROR: The following lock update constraints could not be satisfied:",
        "certifi==2021.5.30",
        "charset-normalizer==2.0.6",
        "idna==3.2",
        "requests==2.26",
        "urllib3<1.16",
        "Encountered 1 error updating {lock_file_path}:".format(lock_file_path=lock_file_path),
    ] == error_lines[:9]
    assert re.match(
        r"^1\.\) {platform}: pid [\d]+ -> ".format(
            platform=LocalInterpreter.create(PythonInterpreter.from_binary(py310)).platform.tag
        ),
        error_lines[9],
    )

    # The pip legacy resolver, though is not strict and will let us get away with this.
    updated_lock_file_path = os.path.join(str(tmpdir), "lock.updated")
    lockfile.store(
        attr.evolve(UPDATE_LOCKFILE, resolver_version=ResolverVersion.PIP_LEGACY),
        updated_lock_file_path,
    )
    result = run_lock_update_for_py310("-p", "urllib3<1.16", updated_lock_file_path)
    result.assert_success()
    assert not result.output
    assert (
        "Updated urllib3 from 1.25.11 to 1.15.1 in lock generated by "
        "cp38-cp38-manylinux_2_33_x86_64.\n" == result.error
    )


DUAL_UPDATE_LOCKFILE_CONTENTS = """\
{
  "allow_builds": true,
  "allow_prereleases": false,
  "allow_wheels": true,
  "build_isolation": true,
  "constraints": [],
  "locked_resolves": [
    {
      "locked_requirements": [
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "5f08ba37b662b9a1d9bcabb457d77eaac4b3c755e623ed77dfe2cd2eba60f6af",
              "url": "https://files.pythonhosted.org/packages/83/aa/c90c4776c8550d2a1a51b9cefeba46f6f158049e4899bfbf97936d3080d6/p537-1.0.4-cp37-cp37m-macosx_10_13_x86_64.whl"
            }
          ],
          "project_name": "p537",
          "requires_dists": [],
          "requires_python": null,
          "version": "1.0.4"
        }
      ],
      "platform_tag": [
        "cp37",
        "cp37m",
        "macosx_10_13_x86_64"
      ]
    },
    {
      "locked_requirements": [
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "20129f25683fab2099d954379fecd36c13ccc0cc0159eaf59afee53a23d749f1",
              "url": "https://files.pythonhosted.org/packages/7c/39/fcd0a978eb327ce8d170ee763264cee1a3a43b0e5f962312d4a37567523d/p537-1.0.4-cp37-cp37m-manylinux1_x86_64.whl"
            }
          ],
          "project_name": "p537",
          "requires_dists": [],
          "requires_python": null,
          "version": "1.0.4"
        }
      ],
      "platform_tag": [
        "cp37",
        "cp37m",
        "manylinux2014_x86_64"
      ]
    }
  ],
  "pex_version": "2.1.50",
  "prefer_older_binary": false,
  "requirements": [
    "p537"
  ],
  "requires_python": [],
  "resolver_version": "pip-2020-resolver",
  "style": "strict",
  "transitive": true,
  "use_pep517": null
}
"""


DUAL_UPDATE_LOCKFILE = lockfile.loads(DUAL_UPDATE_LOCKFILE_CONTENTS)


def test_update_partial(tmpdir):
    # type: (Any) -> None
    # The p537 project was created for Pex --platform tests and we know there will be no releases
    # past 1.0.4; so an unconstrained lock update should be a noop.
    lock_file_path = write_lock_file(tmpdir, DUAL_UPDATE_LOCKFILE_CONTENTS)
    result = run_lock_update(
        "--platform",
        "macosx-10.13-x86_64-cp-37-m",
        "--platform",
        "linux-x86_64-cp-37-m",
        lock_file_path,
    )
    result.assert_success()
    assert DUAL_UPDATE_LOCKFILE == lockfile.load(lock_file_path)

    # By default, lock updates are strict: all locked resolves must be updated at once.
    result = run_lock_update(
        "--platform",
        "macosx-10.13-x86_64-cp-37-m",
        lock_file_path,
    )
    result.assert_failure()
    assert [
        (
            "This lock update is --strict but the following platforms present in {lock_file_path} "
            "were not found on the local machine:".format(lock_file_path=lock_file_path)
        ),
        "+ cp37-cp37m-manylinux2014_x86_64",
        "You might be able to correct this by adjusting target options like --python-path or else "
        "by relaxing the update to be --non-strict.",
    ] == result.error.splitlines()

    result = run_lock_update(
        "--platform",
        "macosx-10.13-x86_64-cp-37-m",
        "--non-strict",
        lock_file_path,
    )
    result.assert_success()
    assert DUAL_UPDATE_LOCKFILE == lockfile.load(lock_file_path)


def test_excludes_pep517_build_requirements_issue_1565(tmpdir):
    # type: (Any) -> None

    # Here we resolve ansicolors 1.0.2 and find 2020.12.3 which are both pure legacy sdist
    # distributions that will need to download build requirements using Pip since we force PEP-517.
    # The cowsay 4.0 requirement is satisfied by a universal wheel and has no build requirements as
    # a result.

    result = run_pex3(
        "lock",
        "create",
        "ansicolors==1.0.2",
        "find==2020.12.3",
        "cowsay==4.0",
        "--force-pep517",
    )
    result.assert_success()
    lock = lockfile.loads(result.output)

    assert 1 == len(lock.locked_resolves)
    assert (
        SortedTuple(
            [
                LockedRequirement.create(
                    pin=Pin(
                        project_name=ProjectName(project_name="ansicolors"),
                        version=Version(version="1.0.2"),
                    ),
                    artifact=Artifact.from_url(
                        url=(
                            "https://files.pythonhosted.org/packages/ac/c1/"
                            "e21f0a1258ff927d124a72179669dcc7efcb57b22df8cd0e49ed8f1a308c/"
                            "ansicolors-1.0.2.tar.gz"
                        ),
                        fingerprint=Fingerprint(
                            algorithm="sha256",
                            hash="7664530bb992e3847b61e3aab1580b4df9ed00c5898e80194a9933bc9c80950a",
                        ),
                    ),
                ),
                LockedRequirement.create(
                    pin=Pin(
                        project_name=ProjectName(project_name="find"),
                        version=Version(version="2020.12.3"),
                    ),
                    artifact=Artifact.from_url(
                        url=(
                            "https://files.pythonhosted.org/packages/91/1c/"
                            "90cac4602ec146ce6f055b2e9598f46da08e941dd860f0498af764407b7e/"
                            "find-2020.12.3.tar.gz"
                        ),
                        fingerprint=Fingerprint(
                            algorithm="sha256",
                            hash="7dadadb63e13de019463f13d83e0e0567a963cad99a568d0f0001ac1104d8210",
                        ),
                    ),
                ),
                LockedRequirement.create(
                    pin=Pin(
                        project_name=ProjectName(project_name="cowsay"),
                        version=Version(version="4"),
                    ),
                    artifact=Artifact.from_url(
                        url=(
                            "https://files.pythonhosted.org/packages/b7/65/"
                            "38f31ef16efc312562f68732098d6f7ba3b2c108a4aaa8ac8ba673ee0871/"
                            "cowsay-4.0-py2.py3-none-any.whl"
                        ),
                        fingerprint=Fingerprint(
                            algorithm="sha256",
                            hash="2594b11d6624fff4bf5147b6bdd510ada54a7b5b4e3f2b15ac2a6d3cf99e0bf8",
                        ),
                    ),
                ),
            ]
        )
        == lock.locked_resolves[0].locked_requirements
    )


LEGACY_UNIVERSAL_LOCKFILE_CONTENTS = """\
{
  "allow_builds": true,
  "allow_prereleases": false,
  "allow_wheels": true,
  "build_isolation": true,
  "constraints": [
    "cffi==1.15",
    "cryptography==35.0.0",
    "ndg-httpsclient==0.5.1",
    "pyasn1==0.4.8",
    "pycparser==2.21",
    "pyopenssl==21",
    "six==1.16"
  ],
  "locked_resolves": [
    {
      "locked_requirements": [
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "45e8636704eacc432a206ac7345a5d3d2c62d95a507ec70d62f23cd91770482a",
              "url": "https://files.pythonhosted.org/packages/61/51/cff222be618f0e060a6991ab387f9574776fd0711a63b2be80df47ec5fad/cffi-1.15.0-cp39-cp39-macosx_10_9_x86_64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "920f0d66a896c2d99f0adbb391f990a84091179542c205fa53ce5787aff87954",
              "url": "https://files.pythonhosted.org/packages/00/9e/92de7e1217ccc3d5f352ba21e52398372525765b2e0c4530e6eb2ba9282a/cffi-1.15.0.tar.gz"
            },
            {
              "algorithm": "sha256",
              "hash": "2a23af14f408d53d5e6cd4e3d9a24ff9e05906ad574822a10563efcef137979a",
              "url": "https://files.pythonhosted.org/packages/03/31/b714d1f35e896fa36c302e024a9ccad3c6952660bcbb1a43188ef20f3ec3/cffi-1.15.0-cp39-cp39-win32.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "6dc2737a3674b3e344847c8686cf29e500584ccad76204efea14f451d4cc669a",
              "url": "https://files.pythonhosted.org/packages/39/02/960252ec9b39840e20a279de29a6fda9b4e49be79e0f32f0cfdf3e61cc4f/cffi-1.15.0-cp39-cp39-manylinux_2_12_i686.manylinux2010_i686.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "31fb708d9d7c3f49a60f04cf5b119aeefe5644daba1cd2a0fe389b674fd1de37",
              "url": "https://files.pythonhosted.org/packages/3e/9b/660d6da900af1976a8b4efea713a7ce9e514bf4659eff9b17f90f00be1cf/cffi-1.15.0-cp39-cp39-macosx_11_0_arm64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "ffaa5c925128e29efbde7301d8ecaf35c8c60ffbcd6a1ffd3a552177c8e5e796",
              "url": "https://files.pythonhosted.org/packages/6a/5e/d33fdd7461fba6e3b0f8fc4141eba410be16af81cf1ed32223a40abe27ac/cffi-1.15.0-cp39-cp39-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "ef1f279350da2c586a69d32fc8733092fd32cc8ac95139a00377841f59a3f8d8",
              "url": "https://files.pythonhosted.org/packages/93/bc/a6b9abd8f692278a8e63759136f47ce69e564a7bcfa7ae7e5561243c74f3/cffi-1.15.0-cp39-cp39-manylinux_2_17_s390x.manylinux2014_s390x.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "3773c4d81e6e818df2efbc7dd77325ca0dcb688116050fb2b3011218eda36139",
              "url": "https://files.pythonhosted.org/packages/bd/92/25f744cbe55e7e54b35f256f9fdd50a590c434cf47afb78b8a6278a87c2d/cffi-1.15.0-cp39-cp39-win_amd64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "3f7d084648d77af029acb79a0ff49a0ad7e9d09057a9bf46596dac9514dc07df",
              "url": "https://files.pythonhosted.org/packages/de/a9/ab4725702c9e5b77643136228a983194fa6e39ea387d964b3c827159d780/cffi-1.15.0-cp39-cp39-manylinux_2_17_ppc64le.manylinux2014_ppc64le.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "74fdfdbfdc48d3f47148976f49fab3251e550a8720bebc99bf1483f5bfb5db3e",
              "url": "https://files.pythonhosted.org/packages/e2/25/00fd291e0872d43dabe070e7b761ba37453a1a94bd6e28c31b73112d8f0c/cffi-1.15.0-cp39-cp39-manylinux_2_12_x86_64.manylinux2010_x86_64.whl"
            }
          ],
          "project_name": "cffi",
          "requires_dists": [
            "pycparser"
          ],
          "requires_python": null,
          "version": "1.15"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "d57e0cdc1b44b6cdf8af1d01807db06886f10177469312fbde8f44ccbb284bc9",
              "url": "https://files.pythonhosted.org/packages/21/d8/ac396584e4559711240018bef74f7359c1dc769febb49973ff0ec397e7bb/cryptography-35.0.0-cp36-abi3-macosx_10_10_x86_64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "4a2d0e0acc20ede0f06ef7aa58546eee96d2592c00f450c9acb89c5879b61992",
              "url": "https://files.pythonhosted.org/packages/07/fa/f63509370561201ffa852e4f3fb105c76ced6927f951e4cc6a3973d1a527/cryptography-35.0.0-cp36-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "c10c797ac89c746e488d2ee92bd4abd593615694ee17b2500578b63cad6b93a8",
              "url": "https://files.pythonhosted.org/packages/0d/7b/355c4a20149417ddae61090089c23d42c7e138f33b37bd62f63638f3982f/cryptography-35.0.0-cp36-abi3-win32.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "9933f28f70d0517686bd7de36166dda42094eac49415459d9bdf5e7df3e0086d",
              "url": "https://files.pythonhosted.org/packages/10/91/90b8d4cd611ac2aa526290ae4b4285aa5ea57ee191c63c2f3d04170d7683/cryptography-35.0.0.tar.gz"
            },
            {
              "algorithm": "sha256",
              "hash": "ced40344e811d6abba00295ced98c01aecf0c2de39481792d87af4fa58b7b4d6",
              "url": "https://files.pythonhosted.org/packages/79/92/7238415a8a624dd74fcb0603fcb222df399210b4713adf8d82e16fd1c76a/cryptography-35.0.0-cp36-abi3-macosx_11_0_arm64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "07bb7fbfb5de0980590ddfc7f13081520def06dc9ed214000ad4372fb4e3c7f6",
              "url": "https://files.pythonhosted.org/packages/7b/1a/bf49bade5080a5cfb226a975c118fc56c3df2878b91809a5030dd87e551b/cryptography-35.0.0-cp36-abi3-manylinux_2_24_x86_64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "7eba2cebca600a7806b893cb1d541a6e910afa87e97acf2021a22b32da1df52d",
              "url": "https://files.pythonhosted.org/packages/83/7c/eb142fff52eb1dda06eaa32ceceec2f9019711dd00c4a12bd9312930a3cc/cryptography-35.0.0-cp36-abi3-musllinux_1_1_aarch64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "7075b304cd567694dc692ffc9747f3e9cb393cc4aa4fb7b9f3abd6f5c4e43588",
              "url": "https://files.pythonhosted.org/packages/93/4b/8f402b9b22cec331d00c6ec2f26184db6e78f53ba24abba8f51b4416bb7b/cryptography-35.0.0-cp36-abi3-win_amd64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "2d69645f535f4b2c722cfb07a8eab916265545b3475fdb34e0be2f4ee8b0b15e",
              "url": "https://files.pythonhosted.org/packages/94/bd/0d36bb113967ab8bc75f58d692846fd27ed64b8d5a7436a672b66976f802/cryptography-35.0.0-cp36-abi3-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "54b2605e5475944e2213258e0ab8696f4f357a31371e538ef21e8d61c843c28d",
              "url": "https://files.pythonhosted.org/packages/c6/dc/4ca9999befed87830c9ecdf9d2e85019b4090f6439754ee9308e1dafba06/cryptography-35.0.0-cp36-abi3-manylinux_2_12_x86_64.manylinux2010_x86_64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "7b7ceeff114c31f285528ba8b390d3e9cfa2da17b56f11d366769a807f17cbaa",
              "url": "https://files.pythonhosted.org/packages/d5/7d/0d8895b3b4aac0cab30a5c285f9a7fc381792e66f6c8d0c055b55259e0d7/cryptography-35.0.0-cp36-abi3-manylinux_2_17_aarch64.manylinux2014_aarch64.manylinux_2_24_aarch64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "18d90f4711bf63e2fb21e8c8e51ed8189438e6b35a6d996201ebd98a26abbbe6",
              "url": "https://files.pythonhosted.org/packages/eb/b2/1812dfe3eefa9256e565c0c81bf2ae40698fc174e8407996d14a63faa126/cryptography-35.0.0-cp36-abi3-musllinux_1_1_x86_64.whl"
            }
          ],
          "project_name": "cryptography",
          "requires_dists": [
            "bcrypt>=3.1.5; extra == \\"ssh\\"",
            "black; extra == \\"pep8test\\"",
            "cffi>=1.12",
            "doc8; extra == \\"docstest\\"",
            "flake8-import-order; extra == \\"pep8test\\"",
            "flake8; extra == \\"pep8test\\"",
            "hypothesis!=3.79.2,>=1.11.4; extra == \\"test\\"",
            "iso8601; extra == \\"test\\"",
            "pep8-naming; extra == \\"pep8test\\"",
            "pretend; extra == \\"test\\"",
            "pyenchant>=1.6.11; extra == \\"docstest\\"",
            "pytest-cov; extra == \\"test\\"",
            "pytest-subtests; extra == \\"test\\"",
            "pytest-xdist; extra == \\"test\\"",
            "pytest>=6.2.0; extra == \\"test\\"",
            "pytz; extra == \\"test\\"",
            "setuptools-rust>=0.11.4; extra == \\"sdist\\"",
            "sphinx!=1.8.0,!=3.1.0,!=3.1.1,>=1.6.5; extra == \\"docs\\"",
            "sphinx-rtd-theme; extra == \\"docs\\"",
            "sphinxcontrib-spelling>=4.0.1; extra == \\"docstest\\"",
            "twine>=1.12.0; extra == \\"docstest\\""
          ],
          "requires_python": ">=3.6",
          "version": "35"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "dd174c11d971b6244a891f7be2b32ca9853d3797a72edb34fa5d7b07d8fff7d4",
              "url": "https://files.pythonhosted.org/packages/fb/67/c2f508c00ed2a6911541494504b7cac16fe0b0473912568df65fd1801132/ndg_httpsclient-0.5.1-py3-none-any.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "d72faed0376ab039736c2ba12e30695e2788c4aa569c9c3e3d72131de2592210",
              "url": "https://files.pythonhosted.org/packages/b9/f8/8f49278581cb848fb710a362bfc3028262a82044167684fb64ad068dbf92/ndg_httpsclient-0.5.1.tar.gz"
            }
          ],
          "project_name": "ndg-httpsclient",
          "requires_dists": [
            "PyOpenSSL",
            "pyasn1>=0.1.1"
          ],
          "requires_python": "!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,>=2.7",
          "version": "0.5.1"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "39c7e2ec30515947ff4e87fb6f456dfc6e84857d34be479c9d4a4ba4bf46aa5d",
              "url": "https://files.pythonhosted.org/packages/62/1e/a94a8d635fa3ce4cfc7f506003548d0a2447ae76fd5ca53932970fe3053f/pyasn1-0.4.8-py2.py3-none-any.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "aef77c9fb94a3ac588e87841208bdec464471d9871bd5050a287cc9a475cd0ba",
              "url": "https://files.pythonhosted.org/packages/a4/db/fffec68299e6d7bad3d504147f9094830b704527a7fc098b721d38cc7fa7/pyasn1-0.4.8.tar.gz"
            }
          ],
          "project_name": "pyasn1",
          "requires_dists": [],
          "requires_python": null,
          "version": "0.4.8"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "8ee45429555515e1f6b185e78100aea234072576aa43ab53aefcae078162fca9",
              "url": "https://files.pythonhosted.org/packages/62/d5/5f610ebe421e85889f2e55e33b7f9a6795bd982198517d912eb1c76e1a53/pycparser-2.21-py2.py3-none-any.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "e644fdec12f7872f86c58ff790da456218b10f863970249516d60a5eaca77206",
              "url": "https://files.pythonhosted.org/packages/5e/0b/95d387f5f4433cb0f53ff7ad859bd2c6051051cebbb564f139a999ab46de/pycparser-2.21.tar.gz"
            }
          ],
          "project_name": "pycparser",
          "requires_dists": [],
          "requires_python": "!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,>=2.7",
          "version": "2.21"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "8935bd4920ab9abfebb07c41a4f58296407ed77f04bd1a92914044b848ba1ed6",
              "url": "https://files.pythonhosted.org/packages/85/3a/fe3c98435856a1ed798977981f3da82d2685cf9df97e4d9546340d2b83db/pyOpenSSL-21.0.0-py2.py3-none-any.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "5e2d8c5e46d0d865ae933bef5230090bdaf5506281e9eec60fa250ee80600cb3",
              "url": "https://files.pythonhosted.org/packages/54/9a/2a43c5dbf4507f86f7c43cba4195d5e25a81c988fd7b0ea779dfc9c6973f/pyOpenSSL-21.0.0.tar.gz"
            }
          ],
          "project_name": "pyopenssl",
          "requires_dists": [
            "cryptography>=3.3",
            "flaky; extra == \\"test\\"",
            "pretend; extra == \\"test\\"",
            "pytest>=3.0.1; extra == \\"test\\"",
            "six>=1.5.2",
            "sphinx-rtd-theme; extra == \\"docs\\"",
            "sphinx; extra == \\"docs\\""
          ],
          "requires_python": "!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*,!=3.5.*,>=2.7",
          "version": "21"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "66cbb850987e47177a3b4112392490bcb76eb75b37cc53da007e35f3ec894bc1",
              "url": "https://files.pythonhosted.org/packages/32/0e/11cfb3a5e269605d0bbe3bbca9845da9b57aed90e75bd489e5e7e3509c13/requests-2.5.0-py2.py3-none-any.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "d2daef4919fc87262b8b3cb5a9d214cac8ce1e50950f8423bbc1d31c2e63d38e",
              "url": "https://files.pythonhosted.org/packages/c8/fb/d14d1c5166a8449d36c9a3b2656706c506a2cf261d37a79d16c18c37b646/requests-2.5.0.tar.gz"
            }
          ],
          "project_name": "requests",
          "requires_dists": [
            "ndg-httpsclient; extra == \\"security\\"",
            "pyOpenSSL; extra == \\"security\\"",
            "pyasn1; extra == \\"security\\""
          ],
          "requires_python": null,
          "version": "2.5"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "8abb2f1d86890a2dfb989f9a77cfcfd3e47c2a354b01111771326f8aa26e0254",
              "url": "https://files.pythonhosted.org/packages/d9/5a/e7c31adbe875f2abbb91bd84cf2dc52d792b5a01506781dbcf25c91daf11/six-1.16.0-py2.py3-none-any.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "1e61c37477a1626458e36f7b1d82aa5c9b094fa4802892072e49de9c60c4c926",
              "url": "https://files.pythonhosted.org/packages/71/39/171f1c67cd00715f190ba0b100d606d440a28c93c7714febeca8b79af85e/six-1.16.0.tar.gz"
            }
          ],
          "project_name": "six",
          "requires_dists": [],
          "requires_python": "!=3.0.*,!=3.1.*,!=3.2.*,>=2.7",
          "version": "1.16"
        }
      ],
      "platform_tag": [
        "cp310",
        "cp310",
        "manylinux_2_33_x86_64"
      ]
    }
  ],
  "pex_version": "2.1.63",
  "prefer_older_binary": false,
  "requirements": [
    "requests[security]==2.5.0"
  ],
  "requires_python": [
    "==3.9.*"
  ],
  "resolver_version": "pip-legacy-resolver",
  "style": "universal",
  "transitive": true,
  "use_pep517": null
}
"""


PIP_2020_UNIVERSAL_LOCKFILE_CONTENTS = """\
{
  "allow_builds": true,
  "allow_prereleases": false,
  "allow_wheels": true,
  "build_isolation": true,
  "constraints": [
    "cffi==1.15",
    "cryptography==35.0.0",
    "ndg-httpsclient==0.5.1",
    "pyasn1==0.4.8",
    "pycparser==2.21",
    "pyopenssl==21",
    "six==1.16"
  ],
  "locked_resolves": [
    {
      "locked_requirements": [
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "3773c4d81e6e818df2efbc7dd77325ca0dcb688116050fb2b3011218eda36139",
              "url": "https://files.pythonhosted.org/packages/bd/92/25f744cbe55e7e54b35f256f9fdd50a590c434cf47afb78b8a6278a87c2d/cffi-1.15.0-cp39-cp39-win_amd64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "920f0d66a896c2d99f0adbb391f990a84091179542c205fa53ce5787aff87954",
              "url": "https://files.pythonhosted.org/packages/00/9e/92de7e1217ccc3d5f352ba21e52398372525765b2e0c4530e6eb2ba9282a/cffi-1.15.0.tar.gz"
            },
            {
              "algorithm": "sha256",
              "hash": "2a23af14f408d53d5e6cd4e3d9a24ff9e05906ad574822a10563efcef137979a",
              "url": "https://files.pythonhosted.org/packages/03/31/b714d1f35e896fa36c302e024a9ccad3c6952660bcbb1a43188ef20f3ec3/cffi-1.15.0-cp39-cp39-win32.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "6dc2737a3674b3e344847c8686cf29e500584ccad76204efea14f451d4cc669a",
              "url": "https://files.pythonhosted.org/packages/39/02/960252ec9b39840e20a279de29a6fda9b4e49be79e0f32f0cfdf3e61cc4f/cffi-1.15.0-cp39-cp39-manylinux_2_12_i686.manylinux2010_i686.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "31fb708d9d7c3f49a60f04cf5b119aeefe5644daba1cd2a0fe389b674fd1de37",
              "url": "https://files.pythonhosted.org/packages/3e/9b/660d6da900af1976a8b4efea713a7ce9e514bf4659eff9b17f90f00be1cf/cffi-1.15.0-cp39-cp39-macosx_11_0_arm64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "45e8636704eacc432a206ac7345a5d3d2c62d95a507ec70d62f23cd91770482a",
              "url": "https://files.pythonhosted.org/packages/61/51/cff222be618f0e060a6991ab387f9574776fd0711a63b2be80df47ec5fad/cffi-1.15.0-cp39-cp39-macosx_10_9_x86_64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "ffaa5c925128e29efbde7301d8ecaf35c8c60ffbcd6a1ffd3a552177c8e5e796",
              "url": "https://files.pythonhosted.org/packages/6a/5e/d33fdd7461fba6e3b0f8fc4141eba410be16af81cf1ed32223a40abe27ac/cffi-1.15.0-cp39-cp39-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "ef1f279350da2c586a69d32fc8733092fd32cc8ac95139a00377841f59a3f8d8",
              "url": "https://files.pythonhosted.org/packages/93/bc/a6b9abd8f692278a8e63759136f47ce69e564a7bcfa7ae7e5561243c74f3/cffi-1.15.0-cp39-cp39-manylinux_2_17_s390x.manylinux2014_s390x.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "3f7d084648d77af029acb79a0ff49a0ad7e9d09057a9bf46596dac9514dc07df",
              "url": "https://files.pythonhosted.org/packages/de/a9/ab4725702c9e5b77643136228a983194fa6e39ea387d964b3c827159d780/cffi-1.15.0-cp39-cp39-manylinux_2_17_ppc64le.manylinux2014_ppc64le.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "74fdfdbfdc48d3f47148976f49fab3251e550a8720bebc99bf1483f5bfb5db3e",
              "url": "https://files.pythonhosted.org/packages/e2/25/00fd291e0872d43dabe070e7b761ba37453a1a94bd6e28c31b73112d8f0c/cffi-1.15.0-cp39-cp39-manylinux_2_12_x86_64.manylinux2010_x86_64.whl"
            }
          ],
          "project_name": "cffi",
          "requires_dists": [
            "pycparser"
          ],
          "requires_python": null,
          "version": "1.15"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "7075b304cd567694dc692ffc9747f3e9cb393cc4aa4fb7b9f3abd6f5c4e43588",
              "url": "https://files.pythonhosted.org/packages/93/4b/8f402b9b22cec331d00c6ec2f26184db6e78f53ba24abba8f51b4416bb7b/cryptography-35.0.0-cp36-abi3-win_amd64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "4a2d0e0acc20ede0f06ef7aa58546eee96d2592c00f450c9acb89c5879b61992",
              "url": "https://files.pythonhosted.org/packages/07/fa/f63509370561201ffa852e4f3fb105c76ced6927f951e4cc6a3973d1a527/cryptography-35.0.0-cp36-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "c10c797ac89c746e488d2ee92bd4abd593615694ee17b2500578b63cad6b93a8",
              "url": "https://files.pythonhosted.org/packages/0d/7b/355c4a20149417ddae61090089c23d42c7e138f33b37bd62f63638f3982f/cryptography-35.0.0-cp36-abi3-win32.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "9933f28f70d0517686bd7de36166dda42094eac49415459d9bdf5e7df3e0086d",
              "url": "https://files.pythonhosted.org/packages/10/91/90b8d4cd611ac2aa526290ae4b4285aa5ea57ee191c63c2f3d04170d7683/cryptography-35.0.0.tar.gz"
            },
            {
              "algorithm": "sha256",
              "hash": "d57e0cdc1b44b6cdf8af1d01807db06886f10177469312fbde8f44ccbb284bc9",
              "url": "https://files.pythonhosted.org/packages/21/d8/ac396584e4559711240018bef74f7359c1dc769febb49973ff0ec397e7bb/cryptography-35.0.0-cp36-abi3-macosx_10_10_x86_64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "ced40344e811d6abba00295ced98c01aecf0c2de39481792d87af4fa58b7b4d6",
              "url": "https://files.pythonhosted.org/packages/79/92/7238415a8a624dd74fcb0603fcb222df399210b4713adf8d82e16fd1c76a/cryptography-35.0.0-cp36-abi3-macosx_11_0_arm64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "07bb7fbfb5de0980590ddfc7f13081520def06dc9ed214000ad4372fb4e3c7f6",
              "url": "https://files.pythonhosted.org/packages/7b/1a/bf49bade5080a5cfb226a975c118fc56c3df2878b91809a5030dd87e551b/cryptography-35.0.0-cp36-abi3-manylinux_2_24_x86_64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "7eba2cebca600a7806b893cb1d541a6e910afa87e97acf2021a22b32da1df52d",
              "url": "https://files.pythonhosted.org/packages/83/7c/eb142fff52eb1dda06eaa32ceceec2f9019711dd00c4a12bd9312930a3cc/cryptography-35.0.0-cp36-abi3-musllinux_1_1_aarch64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "2d69645f535f4b2c722cfb07a8eab916265545b3475fdb34e0be2f4ee8b0b15e",
              "url": "https://files.pythonhosted.org/packages/94/bd/0d36bb113967ab8bc75f58d692846fd27ed64b8d5a7436a672b66976f802/cryptography-35.0.0-cp36-abi3-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "54b2605e5475944e2213258e0ab8696f4f357a31371e538ef21e8d61c843c28d",
              "url": "https://files.pythonhosted.org/packages/c6/dc/4ca9999befed87830c9ecdf9d2e85019b4090f6439754ee9308e1dafba06/cryptography-35.0.0-cp36-abi3-manylinux_2_12_x86_64.manylinux2010_x86_64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "7b7ceeff114c31f285528ba8b390d3e9cfa2da17b56f11d366769a807f17cbaa",
              "url": "https://files.pythonhosted.org/packages/d5/7d/0d8895b3b4aac0cab30a5c285f9a7fc381792e66f6c8d0c055b55259e0d7/cryptography-35.0.0-cp36-abi3-manylinux_2_17_aarch64.manylinux2014_aarch64.manylinux_2_24_aarch64.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "18d90f4711bf63e2fb21e8c8e51ed8189438e6b35a6d996201ebd98a26abbbe6",
              "url": "https://files.pythonhosted.org/packages/eb/b2/1812dfe3eefa9256e565c0c81bf2ae40698fc174e8407996d14a63faa126/cryptography-35.0.0-cp36-abi3-musllinux_1_1_x86_64.whl"
            }
          ],
          "project_name": "cryptography",
          "requires_dists": [
            "bcrypt>=3.1.5; extra == \\"ssh\\"",
            "black; extra == \\"pep8test\\"",
            "cffi>=1.12",
            "doc8; extra == \\"docstest\\"",
            "flake8-import-order; extra == \\"pep8test\\"",
            "flake8; extra == \\"pep8test\\"",
            "hypothesis!=3.79.2,>=1.11.4; extra == \\"test\\"",
            "iso8601; extra == \\"test\\"",
            "pep8-naming; extra == \\"pep8test\\"",
            "pretend; extra == \\"test\\"",
            "pyenchant>=1.6.11; extra == \\"docstest\\"",
            "pytest-cov; extra == \\"test\\"",
            "pytest-subtests; extra == \\"test\\"",
            "pytest-xdist; extra == \\"test\\"",
            "pytest>=6.2.0; extra == \\"test\\"",
            "pytz; extra == \\"test\\"",
            "setuptools-rust>=0.11.4; extra == \\"sdist\\"",
            "sphinx!=1.8.0,!=3.1.0,!=3.1.1,>=1.6.5; extra == \\"docs\\"",
            "sphinx-rtd-theme; extra == \\"docs\\"",
            "sphinxcontrib-spelling>=4.0.1; extra == \\"docstest\\"",
            "twine>=1.12.0; extra == \\"docstest\\""
          ],
          "requires_python": ">=3.6",
          "version": "35"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "dd174c11d971b6244a891f7be2b32ca9853d3797a72edb34fa5d7b07d8fff7d4",
              "url": "https://files.pythonhosted.org/packages/fb/67/c2f508c00ed2a6911541494504b7cac16fe0b0473912568df65fd1801132/ndg_httpsclient-0.5.1-py3-none-any.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "d72faed0376ab039736c2ba12e30695e2788c4aa569c9c3e3d72131de2592210",
              "url": "https://files.pythonhosted.org/packages/b9/f8/8f49278581cb848fb710a362bfc3028262a82044167684fb64ad068dbf92/ndg_httpsclient-0.5.1.tar.gz"
            }
          ],
          "project_name": "ndg-httpsclient",
          "requires_dists": [
            "PyOpenSSL",
            "pyasn1>=0.1.1"
          ],
          "requires_python": "!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,>=2.7",
          "version": "0.5.1"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "39c7e2ec30515947ff4e87fb6f456dfc6e84857d34be479c9d4a4ba4bf46aa5d",
              "url": "https://files.pythonhosted.org/packages/62/1e/a94a8d635fa3ce4cfc7f506003548d0a2447ae76fd5ca53932970fe3053f/pyasn1-0.4.8-py2.py3-none-any.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "aef77c9fb94a3ac588e87841208bdec464471d9871bd5050a287cc9a475cd0ba",
              "url": "https://files.pythonhosted.org/packages/a4/db/fffec68299e6d7bad3d504147f9094830b704527a7fc098b721d38cc7fa7/pyasn1-0.4.8.tar.gz"
            }
          ],
          "project_name": "pyasn1",
          "requires_dists": [],
          "requires_python": null,
          "version": "0.4.8"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "8ee45429555515e1f6b185e78100aea234072576aa43ab53aefcae078162fca9",
              "url": "https://files.pythonhosted.org/packages/62/d5/5f610ebe421e85889f2e55e33b7f9a6795bd982198517d912eb1c76e1a53/pycparser-2.21-py2.py3-none-any.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "e644fdec12f7872f86c58ff790da456218b10f863970249516d60a5eaca77206",
              "url": "https://files.pythonhosted.org/packages/5e/0b/95d387f5f4433cb0f53ff7ad859bd2c6051051cebbb564f139a999ab46de/pycparser-2.21.tar.gz"
            }
          ],
          "project_name": "pycparser",
          "requires_dists": [],
          "requires_python": "!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,>=2.7",
          "version": "2.21"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "8935bd4920ab9abfebb07c41a4f58296407ed77f04bd1a92914044b848ba1ed6",
              "url": "https://files.pythonhosted.org/packages/85/3a/fe3c98435856a1ed798977981f3da82d2685cf9df97e4d9546340d2b83db/pyOpenSSL-21.0.0-py2.py3-none-any.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "5e2d8c5e46d0d865ae933bef5230090bdaf5506281e9eec60fa250ee80600cb3",
              "url": "https://files.pythonhosted.org/packages/54/9a/2a43c5dbf4507f86f7c43cba4195d5e25a81c988fd7b0ea779dfc9c6973f/pyOpenSSL-21.0.0.tar.gz"
            }
          ],
          "project_name": "pyopenssl",
          "requires_dists": [
            "cryptography>=3.3",
            "flaky; extra == \\"test\\"",
            "pretend; extra == \\"test\\"",
            "pytest>=3.0.1; extra == \\"test\\"",
            "six>=1.5.2",
            "sphinx-rtd-theme; extra == \\"docs\\"",
            "sphinx; extra == \\"docs\\""
          ],
          "requires_python": "!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*,!=3.5.*,>=2.7",
          "version": "21"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "66cbb850987e47177a3b4112392490bcb76eb75b37cc53da007e35f3ec894bc1",
              "url": "https://files.pythonhosted.org/packages/32/0e/11cfb3a5e269605d0bbe3bbca9845da9b57aed90e75bd489e5e7e3509c13/requests-2.5.0-py2.py3-none-any.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "d2daef4919fc87262b8b3cb5a9d214cac8ce1e50950f8423bbc1d31c2e63d38e",
              "url": "https://files.pythonhosted.org/packages/c8/fb/d14d1c5166a8449d36c9a3b2656706c506a2cf261d37a79d16c18c37b646/requests-2.5.0.tar.gz"
            }
          ],
          "project_name": "requests",
          "requires_dists": [
            "ndg-httpsclient; extra == \\"security\\"",
            "pyOpenSSL; extra == \\"security\\"",
            "pyasn1; extra == \\"security\\""
          ],
          "requires_python": null,
          "version": "2.5"
        },
        {
          "artifacts": [
            {
              "algorithm": "sha256",
              "hash": "8abb2f1d86890a2dfb989f9a77cfcfd3e47c2a354b01111771326f8aa26e0254",
              "url": "https://files.pythonhosted.org/packages/d9/5a/e7c31adbe875f2abbb91bd84cf2dc52d792b5a01506781dbcf25c91daf11/six-1.16.0-py2.py3-none-any.whl"
            },
            {
              "algorithm": "sha256",
              "hash": "1e61c37477a1626458e36f7b1d82aa5c9b094fa4802892072e49de9c60c4c926",
              "url": "https://files.pythonhosted.org/packages/71/39/171f1c67cd00715f190ba0b100d606d440a28c93c7714febeca8b79af85e/six-1.16.0.tar.gz"
            }
          ],
          "project_name": "six",
          "requires_dists": [],
          "requires_python": "!=3.0.*,!=3.1.*,!=3.2.*,>=2.7",
          "version": "1.16"
        }
      ],
      "platform_tag": [
        "cp310",
        "cp310",
        "manylinux_2_35_x86_64"
      ]
    }
  ],
  "pex_version": "2.1.73",
  "prefer_older_binary": false,
  "requirements": [
    "requests[security]==2.5.0"
  ],
  "requires_python": [
    "==3.9.*"
  ],
  "resolver_version": "pip-2020-resolver",
  "style": "universal",
  "transitive": true,
  "use_pep517": null
}
"""

# N.B.: These two locks have the same contents but differing artifact order. The Pip legacy resolver
# sorts cffi and cryptography mac wheels before win, and the 2020 resolver does the reverse.
EXPECTED_LOCKFILES = {
    ResolverVersion.PIP_LEGACY: lockfile.loads(LEGACY_UNIVERSAL_LOCKFILE_CONTENTS),
    ResolverVersion.PIP_2020: lockfile.loads(PIP_2020_UNIVERSAL_LOCKFILE_CONTENTS),
}


@pytest.mark.skipif(
    PY_VER < (3, 6),
    reason="Some sdists in this lock use f-strings in their builds which requires >=3.6",
)
@pytest.mark.parametrize(
    ["resolver_version", "expected_lockfile"],
    [
        pytest.param(
            resolver_version, EXPECTED_LOCKFILES.get(resolver_version), id=resolver_version.value
        )
        for resolver_version in ResolverVersion.values()
    ],
)
def test_universal_lock(
    tmpdir,  # type: Any
    resolver_version,  # type: ResolverVersion.Value
    expected_lockfile,  # type: Lockfile
):
    # type: (...) -> None

    constraints_file = os.path.join(str(tmpdir), "constraints.txt")
    with open(constraints_file, "w") as fp:
        fp.write(
            dedent(
                """\
                cffi==1.15
                cryptography==35.0.0
                ndg-httpsclient==0.5.1
                pyasn1==0.4.8
                pycparser==2.21
                pyopenssl==21
                six==1.16
                """
            )
        )
    result = run_pex3(
        "lock",
        "create",
        "--style",
        "universal",
        "--resolver-version",
        resolver_version.value,
        "--interpreter-constraint",
        "==3.9.*",
        "requests[security]==2.5.0",
        "--constraints",
        os.path.basename(constraints_file),
        cwd=os.path.dirname(constraints_file),
    )
    result.assert_success()
    lock = lockfile.loads(result.output)

    platform_tag = PythonInterpreter.get().identity.supported_tags[0]
    assert (
        attr.evolve(
            expected_lockfile,
            pex_version=__version__,
            locked_resolves=SortedTuple(
                attr.evolve(locked_resolve, platform_tag=platform_tag)
                for locked_resolve in expected_lockfile.locked_resolves
            ),
        )
        == lock
    )
