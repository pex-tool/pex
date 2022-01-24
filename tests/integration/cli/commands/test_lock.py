# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import subprocess
import sys

import pytest

from pex.cli.commands import lockfile
from pex.cli.commands.lockfile import Lockfile
from pex.distribution_target import DistributionTarget
from pex.interpreter import PythonInterpreter
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import Artifact, Fingerprint, LockedRequirement, Pin
from pex.resolve.resolver_configuration import ResolverVersion
from pex.resolve.testing import normalize_locked_resolve
from pex.sorted_tuple import SortedTuple
from pex.testing import PY310, IntegResults, ensure_python_interpreter, make_env
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import Any, Optional
else:
    from pex.third_party import attr


def run_pex3(
    *args,  # type: str
    **env  # type: Optional[str]
):
    # type: (...) -> IntegResults
    process = subprocess.Popen(
        args=[sys.executable, "-mpex.cli"] + list(args),
        env=make_env(**env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate()
    return IntegResults(
        output=stdout.decode("utf-8"), error=stderr.decode("utf-8"), return_code=process.returncode
    )


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

    def create_lock(style):
        # type: (str) -> LockedRequirement
        lock_file = os.path.join(str(tmpdir), "{}.lock".format(style))
        run_pex3(
            "lock", "create", "ansicolors==1.1.8", "-o", lock_file, "--style", style
        ).assert_success()
        lock = lockfile.load(lock_file)
        assert 1 == len(lock.locked_resolves)
        locked_resolve = lock.locked_resolves[0]
        assert 1 == len(locked_resolve.locked_requirements)
        return locked_resolve.locked_requirements[0]

    assert not create_lock("strict").additional_artifacts

    # We should have 2 total artifacts for sources lock since we know ansicolors 1.1.8 provides
    # both a universal wheel and an sdist.
    assert 1 == len(create_lock("sources").additional_artifacts)


def test_create_local_unsupported(pex_project_dir):
    # type: (str) -> None

    result = run_pex3("lock", "create", pex_project_dir)
    result.assert_failure()
    assert (
        "Cannot create a lock for project requirements built from local or version controlled "
        "sources. Given 1 such project:\n"
        "1.) local project at {path}\n".format(path=pex_project_dir)
    ) == result.error


def test_create_vcs_unsupported():
    # type: () -> None

    result = run_pex3(
        "lock",
        "create",
        "pex @ git+https://github.com/pantsbuild/pex@473c6ac7",
        "git+https://github.com/pypa/pip@f0f67af3#egg=pip",
    )
    result.assert_failure()
    assert (
        "Cannot create a lock for project requirements built from local or version controlled "
        "sources. Given 2 such projects:\n"
        "1.) git project pex at https://github.com/pantsbuild/pex@473c6ac7\n"
        "2.) git project pip at https://github.com/pypa/pip@f0f67af3\n"
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
    **env  # type: Optional[str]
):
    # type: (...) -> IntegResults
    return run_pex3("lock", "update", *args, **env)


def ensure_py310():
    # type: () -> str
    return ensure_python_interpreter(PY310)


@pytest.fixture
def py310():
    # type: () -> str
    return ensure_py310()


def run_lock_update_for_py310(
    *args,  # type: str
    **env  # type: Optional[str]
):
    # type: (...) -> IntegResults
    py38 = ensure_py310()
    return run_lock_update("--python", py38, *args, **env)


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
            artifact=Artifact(
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
            platform=DistributionTarget.for_interpreter(
                PythonInterpreter.from_binary(py310)
            ).get_supported_tags()[0]
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
                    artifact=Artifact(
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
                    artifact=Artifact(
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
                    artifact=Artifact(
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
