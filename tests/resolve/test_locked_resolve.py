# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

import pytest

from pex import targets
from pex.commands.command import Error, try_
from pex.interpreter import PythonInterpreter
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.platforms import Platform
from pex.resolve.locked_resolve import (
    Artifact,
    DownloadableArtifact,
    LockedRequirement,
    LockedResolve,
    Resolved,
)
from pex.resolve.resolved_requirement import Fingerprint, Pin
from pex.sorted_tuple import SortedTuple
from pex.targets import AbbreviatedPlatform, LocalInterpreter, Target
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.packaging.tags import Tag
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Union


@pytest.fixture
def current_target():
    # type: () -> Target
    return targets.current()


@pytest.fixture
def py37_target(py37):
    # type: (PythonInterpreter) -> Target
    return LocalInterpreter.create(py37)


@pytest.fixture
def py310_target(py310):
    # type: (PythonInterpreter) -> Target
    return LocalInterpreter.create(py310)


def pin(
    project_name,  # type: str
    version,  # type: str
):
    # type: (...) -> Pin
    return Pin(project_name=ProjectName(project_name), version=Version(version))


def artifact(
    url,  # type: str
    algorithm,  # type: str
    hash,  # type: str
):
    # type: (...) -> Artifact
    return Artifact(url=url, fingerprint=Fingerprint(algorithm=algorithm, hash=hash))


def locked_requirements(*locked_requirements):
    # type: (*LockedRequirement) -> SortedTuple[LockedRequirement]
    return SortedTuple(locked_requirements)


def req(requirement):
    # type: (str) -> Requirement
    return Requirement.parse(requirement)


def requirements(*reqs):
    # type: (*str) -> Iterable[Requirement]
    return tuple(req(requirement) for requirement in reqs)


@pytest.fixture
def ansicolors_simple():
    # type: () -> LockedResolve
    return LockedResolve(
        platform_tag=Tag("cp27", "cp27mu", "linux_x86_64"),
        locked_requirements=locked_requirements(
            LockedRequirement.create(
                pin=pin("ansicolors", "1.1.7"),
                artifact=artifact(
                    url="https://example.org/ansicolors-1.1.7-py2.py3-none-any.whl",
                    algorithm="blake256",
                    hash="cafebabe",
                ),
                additional_artifacts=[
                    artifact(
                        url="https://example.org/ansicolors-1.1.7.tar.gz",
                        algorithm="sha256",
                        hash="cafebabe",
                    ),
                ],
            ),
            LockedRequirement.create(
                pin=pin("ansicolors", "1.1.8"),
                artifact=artifact(
                    url="https://example.org/ansicolors-1.1.8.tar.gz",
                    algorithm="md5",
                    hash="cafebabe",
                ),
            ),
        ),
    )


def assert_resolved(
    result,  # type: Union[Resolved, Error]
    *downloadable_artifacts  # type: DownloadableArtifact
):
    # type: (...) -> None
    assert SortedTuple(downloadable_artifacts) == try_(result).downloadable_artifacts


def test_build(
    current_target,  # type: Target
    ansicolors_simple,  # type: LockedResolve
):
    # type: (...) -> None
    assert_resolved(
        ansicolors_simple.resolve(current_target, [req("ansicolors")]),
        DownloadableArtifact.create(
            pin=pin("ansicolors", "1.1.8"),
            artifact=artifact(
                url="https://example.org/ansicolors-1.1.8.tar.gz",
                algorithm="md5",
                hash="cafebabe",
            ),
            satisfied_direct_requirements=requirements("ansicolors"),
        ),
    )
    assert_resolved(
        ansicolors_simple.resolve(current_target, [req("ansicolors")], build=False),
        DownloadableArtifact.create(
            pin=pin("ansicolors", "1.1.7"),
            artifact=artifact(
                url="https://example.org/ansicolors-1.1.7-py2.py3-none-any.whl",
                algorithm="blake256",
                hash="cafebabe",
            ),
            satisfied_direct_requirements=requirements("ansicolors"),
        ),
    )


def test_use_wheel(
    current_target,  # type: Target
    ansicolors_simple,  # type: LockedResolve
):
    # type: (...) -> None
    assert_resolved(
        ansicolors_simple.resolve(current_target, [req("ansicolors==1.1.7")]),
        DownloadableArtifact.create(
            pin=pin("ansicolors", "1.1.7"),
            artifact=artifact(
                url="https://example.org/ansicolors-1.1.7-py2.py3-none-any.whl",
                algorithm="blake256",
                hash="cafebabe",
            ),
            satisfied_direct_requirements=requirements("ansicolors==1.1.7"),
        ),
    )
    assert_resolved(
        ansicolors_simple.resolve(current_target, [req("ansicolors==1.1.7")], use_wheel=False),
        DownloadableArtifact.create(
            pin=pin("ansicolors", "1.1.7"),
            artifact=artifact(
                url="https://example.org/ansicolors-1.1.7.tar.gz",
                algorithm="sha256",
                hash="cafebabe",
            ),
            satisfied_direct_requirements=requirements("ansicolors==1.1.7"),
        ),
    )


@pytest.fixture
def ansicolors_exotic():
    # type: () -> LockedResolve
    return LockedResolve(
        platform_tag=Tag("cp37", "cp37m", "exotic"),
        locked_requirements=locked_requirements(
            LockedRequirement.create(
                pin=pin("ansicolors", "1.1.8"),
                artifact=artifact(
                    url="https://example.org/ansicolors-1.1.8-cp37-cp37m-exotic.whl",
                    algorithm="blake256",
                    hash="cafebabe",
                ),
                additional_artifacts=[
                    artifact(
                        url="https://example.org/ansicolors-1.1.8-cp37-abi3-exotic.whl",
                        algorithm="sha256",
                        hash="cafebabe",
                    ),
                    artifact(
                        url="https://example.org/ansicolors-1.1.8.tar.gz",
                        algorithm="md5",
                        hash="cafebabe",
                    ),
                ],
            ),
        ),
    )


def assert_error(
    result,  # type: Union[Resolved, Error]
    expected_error_message,  # type: str
):
    assert Error(expected_error_message.strip()) == result


def platform(plat):
    # type: (str) -> AbbreviatedPlatform
    return AbbreviatedPlatform.create(Platform.create(plat))


def test_invalid_configuration(
    current_target,  # type: Target
    ansicolors_exotic,  # type: LockedResolve
):
    # type: (...) -> None
    assert_error(
        ansicolors_exotic.resolve(
            current_target, [req("ansicolors")], build=False, use_wheel=False
        ),
        "Cannot both ignore wheels (use_wheel=False) and refrain from building distributions "
        "(build=False).",
    )

    platform_target = platform("linux-x86_64-cp-37-m")
    assert_error(
        ansicolors_exotic.resolve(platform_target, [req("ansicolors")], use_wheel=False),
        "Cannot ignore wheels (use_wheel=False) when resolving for a platform: given "
        "{target_description}".format(target_description=platform_target.render_description()),
    )


def test_platform_resolve(ansicolors_exotic):
    # type: (LockedResolve) -> None

    assert_resolved(
        ansicolors_exotic.resolve(platform("exotic-cp-37-m"), [req("ansicolors")]),
        DownloadableArtifact.create(
            pin=pin("ansicolors", "1.1.8"),
            artifact=artifact(
                url="https://example.org/ansicolors-1.1.8-cp37-cp37m-exotic.whl",
                algorithm="blake256",
                hash="cafebabe",
            ),
            satisfied_direct_requirements=requirements("ansicolors"),
        ),
    )

    assert_resolved(
        ansicolors_exotic.resolve(platform("exotic-cp-38-cp38"), [req("ansicolors")]),
        DownloadableArtifact.create(
            pin=pin("ansicolors", "1.1.8"),
            artifact=artifact(
                url="https://example.org/ansicolors-1.1.8-cp37-abi3-exotic.whl",
                algorithm="sha256",
                hash="cafebabe",
            ),
            satisfied_direct_requirements=requirements("ansicolors"),
        ),
    )


def test_not_found(
    current_target,  # type: Target
    ansicolors_exotic,  # type: LockedResolve
):
    # type: (...) -> None
    assert_error(
        ansicolors_exotic.resolve(current_target, [req("requests>1")]),
        dedent(
            """\
            Failed to resolve all requirements for {target_description}:

            Configured with:
                build: True
                use_wheel: True

            Dependency on requests (via: requests>1) not satisfied, no candidates found.
            """
        ).format(target_description=current_target.render_description()),
    )


def test_version_mismatch(
    current_target,  # type: Target
    ansicolors_exotic,  # type: LockedResolve
    ansicolors_simple,  # type: LockedResolve
):
    # type: (...) -> None

    assert_error(
        ansicolors_exotic.resolve(current_target, [req("ansicolors>1,<1.1")]),
        dedent(
            """\
            Failed to resolve all requirements for {target_description}:

            Configured with:
                build: True
                use_wheel: True

            Dependency on ansicolors not satisfied, 1 incompatible candidate found:
            1.) ansicolors 1.1.8 does not satisfy the following requirements:
                <1.1,>1 (via: ansicolors<1.1,>1)
            """
        ).format(target_description=current_target.render_description()),
    )

    assert_error(
        ansicolors_simple.resolve(current_target, [req("ansicolors>1,<1.1")]),
        dedent(
            """\
            Failed to resolve all requirements for {target_description}:

            Configured with:
                build: True
                use_wheel: True

            Dependency on ansicolors not satisfied, 2 incompatible candidates found:
            1.) ansicolors 1.1.7 does not satisfy the following requirements:
                <1.1,>1 (via: ansicolors<1.1,>1)
            2.) ansicolors 1.1.8 does not satisfy the following requirements:
                <1.1,>1 (via: ansicolors<1.1,>1)
            """
        ).format(target_description=current_target.render_description()),
    )


def test_wheel_tag_mismatch(
    current_target,  # type: Target
    ansicolors_exotic,  # type: LockedResolve
):
    # type: (...) -> None
    assert_error(
        ansicolors_exotic.resolve(current_target, [req("ansicolors==1.1.*")], build=False),
        dedent(
            """\
            Failed to resolve all requirements for {target_description}:

            Configured with:
                build: False
                use_wheel: True

            Dependency on ansicolors not satisfied, 1 incompatible candidate found:
            1.) ansicolors 1.1.8 (via: ansicolors==1.1.*) does not have any compatible artifacts:
                https://example.org/ansicolors-1.1.8-cp37-cp37m-exotic.whl
                https://example.org/ansicolors-1.1.8-cp37-abi3-exotic.whl
                https://example.org/ansicolors-1.1.8.tar.gz
            """
        ).format(target_description=current_target.render_description()),
    )

    assert_resolved(
        ansicolors_exotic.resolve(current_target, [req("ansicolors==1.1.*")]),
        DownloadableArtifact.create(
            pin=pin("ansicolors", "1.1.8"),
            artifact=artifact(
                url="https://example.org/ansicolors-1.1.8.tar.gz",
                algorithm="md5",
                hash="cafebabe",
            ),
            satisfied_direct_requirements=requirements("ansicolors==1.1.*"),
        ),
    )


def test_requires_python_mismatch(
    py37_target,  # type: Target
    py310_target,  # type: Target
):
    # type: (...) -> None

    locked_resolve = LockedResolve(
        platform_tag=Tag("cp37", "cp37m", "exotic"),
        locked_requirements=locked_requirements(
            LockedRequirement.create(
                pin=pin("ansicolors", "1.1.7"),
                artifact=artifact(
                    url="https://example.org/ansicolors-1.1.7-py2.py3-none-any.whl",
                    algorithm="blake256",
                    hash="cafebabe",
                ),
                requires_python=SpecifierSet(">=3,<3.10"),
            ),
        ),
    )

    assert_error(
        locked_resolve.resolve(py310_target, [req("ansicolors==1.1.7")]),
        dedent(
            """\
            Failed to resolve all requirements for {target_description}:

            Configured with:
                build: True
                use_wheel: True

            Dependency on ansicolors not satisfied, 1 incompatible candidate found:
            1.) ansicolors 1.1.7 (via: ansicolors==1.1.7) requires Python <3.10,>=3
            """
        ).format(target_description=py310_target.render_description()),
    )

    assert_resolved(
        locked_resolve.resolve(py37_target, [req("ansicolors==1.1.7")]),
        DownloadableArtifact.create(
            pin=pin("ansicolors", "1.1.7"),
            artifact=artifact(
                url="https://example.org/ansicolors-1.1.7-py2.py3-none-any.whl",
                algorithm="blake256",
                hash="cafebabe",
            ),
            satisfied_direct_requirements=requirements("ansicolors==1.1.7"),
        ),
    )


def test_prefer_older_binary(current_target):
    # type: (Target) -> None

    locked_resolve = LockedResolve(
        platform_tag=Tag("cp37", "cp37m", "exotic"),
        locked_requirements=locked_requirements(
            LockedRequirement.create(
                pin=pin("ansicolors", "1.1.7"),
                artifact=artifact(
                    url="https://example.org/ansicolors-1.1.7-py2.py3-none-any.whl",
                    algorithm="blake256",
                    hash="cafebabe",
                ),
            ),
            LockedRequirement.create(
                pin=pin("ansicolors", "1.1.8"),
                artifact=artifact(
                    url="https://example.org/ansicolors-1.1.8.tar.gz",
                    algorithm="sha256",
                    hash="cafebabe",
                ),
            ),
        ),
    )

    assert_resolved(
        locked_resolve.resolve(current_target, [req("ansicolors>1")]),
        DownloadableArtifact.create(
            pin=pin("ansicolors", "1.1.8"),
            artifact=artifact(
                url="https://example.org/ansicolors-1.1.8.tar.gz",
                algorithm="sha256",
                hash="cafebabe",
            ),
            satisfied_direct_requirements=requirements("ansicolors>1"),
        ),
    )

    assert_resolved(
        locked_resolve.resolve(current_target, [req("ansicolors>1")], prefer_older_binary=True),
        DownloadableArtifact.create(
            pin=pin("ansicolors", "1.1.7"),
            artifact=artifact(
                url="https://example.org/ansicolors-1.1.7-py2.py3-none-any.whl",
                algorithm="blake256",
                hash="cafebabe",
            ),
            satisfied_direct_requirements=requirements("ansicolors>1"),
        ),
    )


@pytest.fixture
def cyclic_resolve():
    # type: () -> LockedResolve
    return LockedResolve(
        platform_tag=Tag("cp37", "cp37m", "linux_x86_64"),
        locked_requirements=locked_requirements(
            LockedRequirement.create(
                pin=pin("A", "1.0.0"),
                artifact=artifact("file:///repo/A-1.0.0.tar.gz", "sha256", "cafebabe"),
                requires_dists=requirements("B>=2", "C"),
            ),
            LockedRequirement.create(
                pin=pin("B", "2.0.0"),
                artifact=artifact("file:///repo/B-2.0-py2.py3-none-any.whl", "sha256", "cafebabe"),
                requires_dists=requirements("C"),
            ),
            LockedRequirement.create(
                pin=pin("C", "3.0.0"),
                artifact=artifact("file:///repo/C-3.0.0.tar.gz", "sha256", "cafebabe"),
                requires_dists=requirements("A~=1.0"),
            ),
        ),
    )


def test_transitive(
    current_target,  # type: Target
    cyclic_resolve,  # type: LockedResolve
):
    # type: (...) -> None

    assert_resolved(
        cyclic_resolve.resolve(current_target, [req("A")]),
        DownloadableArtifact.create(
            pin=pin("A", "1.0.0"),
            artifact=artifact("file:///repo/A-1.0.0.tar.gz", "sha256", "cafebabe"),
            satisfied_direct_requirements=requirements("A"),
        ),
        DownloadableArtifact.create(
            pin=pin("B", "2.0.0"),
            artifact=artifact("file:///repo/B-2.0-py2.py3-none-any.whl", "sha256", "cafebabe"),
            satisfied_direct_requirements=requirements(),
        ),
        DownloadableArtifact.create(
            pin=pin("C", "3.0.0"),
            artifact=artifact("file:///repo/C-3.0.0.tar.gz", "sha256", "cafebabe"),
            satisfied_direct_requirements=requirements(),
        ),
    )

    assert_resolved(
        cyclic_resolve.resolve(current_target, [req("A")], transitive=False),
        DownloadableArtifact.create(
            pin=pin("A", "1.0.0"),
            artifact=artifact("file:///repo/A-1.0.0.tar.gz", "sha256", "cafebabe"),
            satisfied_direct_requirements=requirements("A"),
        ),
    )

    assert_resolved(
        cyclic_resolve.resolve(current_target, [req("B")], transitive=False),
        DownloadableArtifact.create(
            pin=pin("B", "2.0.0"),
            artifact=artifact("file:///repo/B-2.0-py2.py3-none-any.whl", "sha256", "cafebabe"),
            satisfied_direct_requirements=requirements("B"),
        ),
    )

    assert_resolved(
        cyclic_resolve.resolve(current_target, [req("C")], transitive=False),
        DownloadableArtifact.create(
            pin=pin("C", "3.0.0"),
            artifact=artifact("file:///repo/C-3.0.0.tar.gz", "sha256", "cafebabe"),
            satisfied_direct_requirements=requirements("C"),
        ),
    )


def test_multiple_errors(
    current_target,  # type: Target
    cyclic_resolve,  # type: LockedResolve
):
    # type: (...) -> None

    assert_error(
        cyclic_resolve.resolve(current_target, [req("A==1.0.1")], use_wheel=False),
        dedent(
            """\
            Failed to resolve all requirements for {target_description}:

            Configured with:
                build: True
                use_wheel: False

            Dependency on a not satisfied, 1 incompatible candidate found:
            1.) a 1 does not satisfy the following requirements:
                ==1.0.1 (via: A==1.0.1)
            
            Dependency on b not satisfied, 1 incompatible candidate found:
            1.) b 2 (via: A==1.0.1 -> B>=2) does not have any compatible artifacts:
                file:///repo/B-2.0-py2.py3-none-any.whl
            """
        ).format(target_description=current_target.render_description()),
    )
