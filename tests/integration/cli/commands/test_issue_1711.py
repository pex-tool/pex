# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.cli.testing import run_pex3
from pex.compatibility import PY3
from pex.interpreter import PythonInterpreter
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve import lockfile
from pex.resolve.locked_resolve import Artifact, LockedRequirement
from pex.resolve.resolved_requirement import Fingerprint
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def pypi_artifact(
    hash,  # type: str
    path,  # type: str
):
    # type: (...) -> Artifact
    return Artifact.from_url(
        url="https://files.pythonhosted.org/packages/{}".format(path),
        fingerprint=Fingerprint(algorithm="sha256", hash=hash),
    )


def test_backtrack_links_preserved(
    tmpdir,  # type: Any
    py37,  # type: PythonInterpreter
):
    # type: (...) -> None

    lock = os.path.join(str(tmpdir), "lock")
    create_lock_args = [
        "lock",
        "create",
        "--resolver-version",
        "pip-2020-resolver",
        "--style",
        "universal",
        "--interpreter-constraint",
        ">=3.7,<3.10",
        "--python-path",
        py37.binary,
        "psutil",
        "psutil<5.5",  # force a back-track
        "-o",
        lock,
        "--indent",
        "2",
    ]

    def lock_as_json():
        with open(lock) as fp:
            return fp.read()

    def assert_psutil_basics():
        # type: () -> LockedRequirement
        lock_file = lockfile.load(lock)
        assert 1 == len(
            lock_file.locked_resolves
        ), "Expected 1 resolve for universal style:\n{json}".format(json=lock_as_json())
        locked_resolve = lock_file.locked_resolves[0]

        locked_requirements_by_project_name = {
            locked_requirement.pin.project_name: locked_requirement
            for locked_requirement in locked_resolve.locked_requirements
        }
        psutil = locked_requirements_by_project_name.get(ProjectName("psutil"))
        assert psutil is not None, "Expected lock to resolve psutil:\n{json}".format(
            json=lock_as_json()
        )
        assert Version("5.4.8") == psutil.pin.version, (
            "Expected lock to resolve psutil to <5.5 due to the second requirement but otherwise "
            "as high as possible, which should be 5.4.8 but was: {version}\n{json}".format(
                version=psutil.pin.version, json=lock_as_json()
            )
        )
        return psutil

    # 1st prove this does the wrong thing on prior broken versions of Pex.
    # N.B.: For some reason, this works with old Pex under Python 2.7; i.e.: It appears Pip behaves
    # differently - likely because of some collection implementation difference.
    if PY3:
        run_pex_command(
            args=["pex==2.1.77", "-c", "pex3", "--"] + create_lock_args
        ).assert_success()
        psutil_old = assert_psutil_basics()
        assert 0 == len(psutil_old.additional_artifacts), (
            "Expected old versions of Pex to incorrectly wipe out the additional artifacts "
            "database when backtracking needs to retrieve saved links later:\n{json}".format(
                json=lock_as_json()
            )
        )

    # Now show it currently works.
    run_pex3(*create_lock_args).assert_success()
    psutil_current = assert_psutil_basics()
    assert {
        pypi_artifact(
            hash="1c71b9716790e202a00ab0931a6d1e25db1aa1198bcacaea2f5329f75d257fff",
            path="50/00/ae52663b879333aa5c65fc9a87ddc24169f8fdd1831762a1ba9c9be7740d/psutil-5.4.8-cp37-cp37m-win_amd64.whl",
        ),
        pypi_artifact(
            hash="bfcea4f189177b2d2ce4a34b03c4ac32c5b4c22e21f5b093d9d315e6e253cd81",
            path="21/1e/fe6731e5f03ddf2e57d5b307f25bba294262bc88e27a0fbefdb3515d1727/psutil-5.4.8-cp37-cp37m-win32.whl",
        ),
        pypi_artifact(
            hash="6e265c8f3da00b015d24b842bfeb111f856b13d24f2c57036582568dc650d6c3",
            path="e3/58/0eae6e4466e5abf779d7e2b71fac7fba5f59e00ea36ddb3ed690419ccb0f/psutil-5.4.8.tar.gz",
        ),
    } == set(psutil_current.iter_artifacts()), (
        "Expected a full set of artifacts even after the lock resolve backtracked from "
        "psutil latest to psutil<5.5 before settling:\n{json}".format(json=lock_as_json())
    )
