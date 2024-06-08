# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path

import pytest

from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pip.log_analyzer import ErrorMessage
from pex.requirements import parse_requirement_string
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.locked_resolve import LockConfiguration, LockStyle
from pex.resolve.locker import Locker, LockResult
from pex.resolve.resolved_requirement import (
    ArtifactURL,
    Fingerprint,
    PartialArtifact,
    Pin,
    ResolvedRequirement,
)
from pex.targets import LocalInterpreter
from pex.typing import TYPE_CHECKING
from testing import data

if TYPE_CHECKING:
    from typing import Any


@pytest.fixture
def locker(tmpdir):
    # type: (Any) -> Locker
    download_dir = os.path.join(str(tmpdir), "downloads")
    return Locker(
        target=LocalInterpreter.create(),
        root_requirements=[parse_requirement_string("wheel")],
        resolver=ConfiguredResolver.default(),
        lock_configuration=LockConfiguration(style=LockStyle.SOURCES),
        download_dir=download_dir,
    )


def analyze_log(
    locker,  # type: Locker
    log_name,  # type: str
):
    # type: (...) -> None
    with open(data.path("pip_logs", log_name)) as fp:
        for line in fp:
            result = locker.analyze(line)
            assert not isinstance(result.data, ErrorMessage)
    locker.analysis_completed()


@pytest.mark.parametrize("pip_version", ["23.2", "23.3.1"])
def test_redirects_dont_stomp_original_index_urls(
    pip_version,  # type: str
    locker,  # type: Locker
):
    # type: (...) -> None

    analyze_log(locker, "issue-2414.pip-{pip_version}.log".format(pip_version=pip_version))

    expected_whl_artifact = PartialArtifact(
        url=ArtifactURL.parse(
            "https://m.devpi.net/root/pypi/%2Bf/55c/570405f142630/wheel-0.43.0-py3-none-any.whl"
        ),
        fingerprint=Fingerprint(
            algorithm="sha256",
            hash="55c570405f142630c6b9f72fe09d9b67cf1477fcf543ae5b8dcb1f5b7377da81",
        ),
        verified=False,
    )
    expected_sdist_artifact = PartialArtifact(
        url=ArtifactURL.parse(
            "https://m.devpi.net/root/pypi/%2Bf/465/ef92c69fa5c5d/wheel-0.43.0.tar.gz"
        ),
        fingerprint=Fingerprint(
            algorithm="sha256",
            hash="465ef92c69fa5c5da2d1cf8ac40559a8c940886afcef87dcf14b9470862f1d85",
        ),
        verified=False,
    )
    expected_wheel_requirement = ResolvedRequirement(
        pin=Pin(ProjectName("wheel"), Version("0.43.0")),
        artifact=expected_whl_artifact,
        additional_artifacts=tuple([expected_sdist_artifact]),
    )
    expected_lock_result = LockResult(
        resolved_requirements=tuple([expected_wheel_requirement]),
        local_projects=(),
    )
    assert expected_lock_result == locker.lock_result
