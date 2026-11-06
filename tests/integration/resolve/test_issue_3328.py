# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pytest

from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.lockfile import json_codec
from pex.venv.virtualenv import Virtualenv
from testing import PY_VER
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(
    PY_VER < (3, 7),
    reason=(
        "The distributions under test have a pdm-backend build dependency that requires "
        "Python >= 23.7."
    ),
)
@pytest.mark.parametrize(
    "requirement_url",
    [
        pytest.param(
            (
                "git+https://github.com/tgolsson/pants-backends"
                "@b60257de38d7bf87622cbdc2a68d0220cf300cb1"
            ),
            id="VCS",
        ),
        pytest.param(
            (
                "https://github.com/tgolsson/pants-backends"
                "/archive/b60257de38d7bf87622cbdc2a68d0220cf300cb1.zip"
            ),
            id="source-archive",
        ),
    ],
)
def test_lock_same_url_different_subdirs(
    tmpdir,  # type: Tempdir
    requirement_url,  # type: str
):
    # type: (...) -> None

    lock_file = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "pants-backend-k8s @ {requirement_url}#subdirectory=pants-plugins/k8s".format(
            requirement_url=requirement_url
        ),
        "pants-backend-mdbook @ {requirement_url}#subdirectory=pants-plugins/mdbook".format(
            requirement_url=requirement_url
        ),
        "--indent",
        "2",
        "-o",
        lock_file,
    ).assert_success()

    lock = json_codec.load(lock_file)
    assert len(lock.locked_resolves) == 1
    locked_resolve = lock.locked_resolves[0]
    locked_requirements_by_project_name = {
        locked_requirement.pin.project_name: locked_requirement
        for locked_requirement in locked_resolve.locked_requirements
    }
    pants_backend_k8s = locked_requirements_by_project_name.pop(ProjectName("pants-backend-k8s"))
    assert Version("0.7.0") == pants_backend_k8s.pin.version
    assert "pants-plugins/k8s" == pants_backend_k8s.artifact.subdirectory

    pants_backend_mdbook = locked_requirements_by_project_name.pop(
        ProjectName("pants-backend-mdbook")
    )
    assert Version("0.8.0") == pants_backend_mdbook.pin.version
    assert "pants-plugins/mdbook" == pants_backend_mdbook.artifact.subdirectory

    venv_dir = tmpdir.join("venv")
    run_pex3("venv", "create", "-d", venv_dir, "--lock", lock_file).assert_success()
    dists_by_project_name = {
        dist.metadata.project_name: dist for dist in Virtualenv(venv_dir).iter_distributions()
    }
    assert (
        Version("0.7.0")
        == dists_by_project_name.pop(ProjectName("pants-backend-k8s")).metadata.version
    )
    assert (
        Version("0.8.0")
        == dists_by_project_name.pop(ProjectName("pants-backend-mdbook")).metadata.version
    )
