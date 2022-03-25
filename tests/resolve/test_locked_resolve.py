# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pex import targets
from pex.interpreter import PythonInterpreter
from pex.pep_425 import CompatibilityTags, TagRank
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pep_508 import MarkerEnvironment
from pex.platforms import Platform
from pex.requirements import VCS
from pex.resolve.locked_resolve import (
    Artifact,
    DownloadableArtifact,
    FileArtifact,
    LockedRequirement,
    LockedResolve,
    RankedArtifact,
    Resolved,
    VCSArtifact,
    _ResolvedArtifact,
)
from pex.resolve.resolved_requirement import Fingerprint, Pin
from pex.result import Error, try_
from pex.sorted_tuple import SortedTuple
from pex.targets import AbbreviatedPlatform, CompletePlatform, LocalInterpreter, Target
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
    # type: (...) -> Union[FileArtifact, VCSArtifact]
    return Artifact.from_url(url=url, fingerprint=Fingerprint(algorithm=algorithm, hash=hash))


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
                    url="https://example.org/ansicolors-1.1.7-1buildtag-py2.py3-none-any.whl",
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
                url="https://example.org/ansicolors-1.1.7-1buildtag-py2.py3-none-any.whl",
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
                url="https://example.org/ansicolors-1.1.7-1buildtag-py2.py3-none-any.whl",
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


def test_constraints(
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
        ansicolors_simple.resolve(
            current_target, [req("ansicolors")], constraints=[req("ansicolors<1.1.8")]
        ),
        DownloadableArtifact.create(
            pin=pin("ansicolors", "1.1.7"),
            artifact=artifact(
                url="https://example.org/ansicolors-1.1.7-1buildtag-py2.py3-none-any.whl",
                algorithm="blake256",
                hash="cafebabe",
            ),
            satisfied_direct_requirements=requirements("ansicolors"),
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


def test_source(
    current_target,  # type: Target
    ansicolors_exotic,  # type: LockedResolve
):
    # type: (...) -> None
    assert_error(
        ansicolors_exotic.resolve(current_target, [req("requests>1")], source="lock.json"),
        dedent(
            """\
            Failed to resolve all requirements for {target_description} from lock.json:

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
                    url="https://example.org/ansicolors-1.1.7-1buildtag-py2.py3-none-any.whl",
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
                url="https://example.org/ansicolors-1.1.7-1buildtag-py2.py3-none-any.whl",
                algorithm="blake256",
                hash="cafebabe",
            ),
            satisfied_direct_requirements=requirements("ansicolors==1.1.7"),
        ),
    )


def test_constraint_mismatch(
    current_target,  # type: Target
    ansicolors_simple,  # type: LockedResolve
):
    # type: (...) -> None
    locked_resolve = LockedResolve(
        platform_tag=Tag("cp37", "cp37m", "exotic"),
        locked_requirements=locked_requirements(
            LockedRequirement.create(
                pin=pin("ansicolors", "1.1.7"),
                artifact=artifact(
                    url="https://example.org/ansicolors-1.1.7-1buildtag-py2.py3-none-any.whl",
                    algorithm="blake256",
                    hash="cafebabe",
                ),
            ),
        ),
    )

    assert_error(
        locked_resolve.resolve(
            current_target, [req("ansicolors")], constraints=[req("ansicolors>=2")]
        ),
        dedent(
            """\
            Failed to resolve all requirements for {target_description}:

            Configured with:
                build: True
                use_wheel: True

            Dependency on ansicolors not satisfied, 1 incompatible candidate found:
            1.) ansicolors 1.1.7 does not satisfy the following requirements:
                >=2 (via: constraint)
            """
        ).format(target_description=current_target.render_description()),
    )

    assert_resolved(
        locked_resolve.resolve(
            current_target, [req("ansicolors")], constraints=[req("irrelevant==1.0.0")]
        ),
        DownloadableArtifact.create(
            pin=pin("ansicolors", "1.1.7"),
            artifact=artifact(
                url="https://example.org/ansicolors-1.1.7-1buildtag-py2.py3-none-any.whl",
                algorithm="blake256",
                hash="cafebabe",
            ),
            satisfied_direct_requirements=requirements("ansicolors"),
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
                    url="https://example.org/ansicolors-1.1.7-1buildtag-py2.py3-none-any.whl",
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
                url="https://example.org/ansicolors-1.1.7-1buildtag-py2.py3-none-any.whl",
                algorithm="blake256",
                hash="cafebabe",
            ),
            satisfied_direct_requirements=requirements("ansicolors>1"),
        ),
    )


def resolved_artifact(
    project_name,  # type: str
    version,  # type: str
    artifact_basename,  # type: str
    rank_value,  # type: int
):
    # type: (...) -> _ResolvedArtifact
    primary_artifact = artifact(
        url="https://example.org/{artifact_basename}".format(artifact_basename=artifact_basename),
        algorithm="sha256",
        hash="cafebabe",
    )
    return _ResolvedArtifact(
        ranked_artifact=RankedArtifact(artifact=primary_artifact, rank=TagRank(rank_value)),
        locked_requirement=LockedRequirement.create(
            pin=pin(project_name, version), artifact=primary_artifact
        ),
    )


def test_resolved_artifact_select_higher_rank():
    specific_wheel_117 = resolved_artifact(
        "ansicolors", "1.1.7", "ansicolors-1.1.7-cp38-cp38-linux_x86_64.whl", 0
    )
    specific_wheel_118 = resolved_artifact(
        "ansicolors", "1.1.8", "ansicolors-1.1.8-cp38-cp38-linux_x86_64.whl", 0
    )

    general_wheel_117 = resolved_artifact(
        "ansicolors", "1.1.7", "ansicolors-1.1.7-py3-none-any.whl", 122
    )
    general_wheel_118 = resolved_artifact(
        "ansicolors", "1.1.8", "ansicolors-1.1.8-py3-none-any.whl", 122
    )

    source_117 = resolved_artifact("ansicolors", "1.1.7", "ansicolors-1.1.7.tar.gz", 123)
    source_118 = resolved_artifact("ansicolors", "1.1.8", "ansicolors-1.1.8.tar.gz", 123)

    # Same rank, different versions.
    assert specific_wheel_118 is specific_wheel_117.select_higher_rank(specific_wheel_118)
    assert specific_wheel_118 is specific_wheel_117.select_higher_rank(
        specific_wheel_118, prefer_older_binary=True
    )
    assert general_wheel_118 is general_wheel_118.select_higher_rank(general_wheel_117)
    assert general_wheel_118 is general_wheel_118.select_higher_rank(
        general_wheel_117, prefer_older_binary=True
    )
    assert source_118 is source_117.select_higher_rank(source_118)
    assert source_118 is source_117.select_higher_rank(source_118, prefer_older_binary=True)

    # Same version, different ranks.
    assert general_wheel_117 is source_117.select_higher_rank(general_wheel_117)
    assert general_wheel_117 is source_117.select_higher_rank(
        general_wheel_117, prefer_older_binary=True
    )
    assert specific_wheel_117 is general_wheel_117.select_higher_rank(specific_wheel_117)
    assert specific_wheel_117 is general_wheel_117.select_higher_rank(
        specific_wheel_117, prefer_older_binary=True
    )

    # Same rank, same version.
    assert source_117 is source_117.select_higher_rank(source_117)
    assert source_117 is source_117.select_higher_rank(source_117, prefer_older_binary=True)

    # Rank and version covariant
    assert specific_wheel_118 is source_117.select_higher_rank(specific_wheel_118)
    assert specific_wheel_118 is source_117.select_higher_rank(
        specific_wheel_118, prefer_older_binary=True
    )

    # Rank and version contravariant all wheel.
    assert general_wheel_118 is general_wheel_118.select_higher_rank(specific_wheel_117)
    assert general_wheel_118 is general_wheel_118.select_higher_rank(
        specific_wheel_117, prefer_older_binary=True
    )

    # Rank and version contravariant mixed source and wheel.
    assert source_118 is source_118.select_higher_rank(specific_wheel_117)
    assert specific_wheel_117 is source_118.select_higher_rank(
        specific_wheel_117, prefer_older_binary=True
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


def test_resolved():
    # type: () -> None

    def assert_resolved(
        expected_target_specificity,  # type: float
        supported_tag_count,  # type: int
        artifact_ranks,  # type: Iterable[int]
    ):
        # type: (...) -> None
        direct_requirements = requirements("foo")

        resolved_artifacts = tuple(
            resolved_artifact(
                project_name="foo",
                version=str(rank),
                artifact_basename="foo-{}.tar.gz".format(rank),
                rank_value=rank,
            )
            for rank in artifact_ranks
        )

        downloadable_artifacts = tuple(
            DownloadableArtifact.create(
                pin=resolved_art.locked_requirement.pin,
                artifact=resolved_art.artifact,
                satisfied_direct_requirements=direct_requirements,
            )
            for resolved_art in resolved_artifacts
        )

        target = CompletePlatform.create(
            MarkerEnvironment(),
            CompatibilityTags.from_strings(
                "py3-none-manylinux_2_{glibc_minor}_x86_64".format(glibc_minor=glibc_minor)
                for glibc_minor in range(supported_tag_count)
            ),
        )

        assert Resolved(
            target_specificity=expected_target_specificity,
            downloadable_artifacts=downloadable_artifacts,
        ) == Resolved.create(
            target=target,
            direct_requirements=direct_requirements,
            downloadable_requirements=resolved_artifacts,
        )

    # For tag ranks of 1, 2, 1 should rank 100% target specific (best match) and 2 should rank 0%
    # (worst match / universal)
    assert_resolved(expected_target_specificity=1.0, supported_tag_count=2, artifact_ranks=[1])
    assert_resolved(expected_target_specificity=0.0, supported_tag_count=2, artifact_ranks=[2])

    # For tag ranks of 1, 2, 3, 2 lands in the middle and should be 50% target specific.
    assert_resolved(expected_target_specificity=0.5, supported_tag_count=3, artifact_ranks=[2])


def test_file_artifact():
    # type: () -> None

    artifact = Artifact.from_url(
        url="file:///repo/A-1.0.0.tar.gz",
        fingerprint=Fingerprint(algorithm="md5", hash="foo"),
    )
    assert isinstance(artifact, FileArtifact)
    assert "A-1.0.0.tar.gz" == artifact.filename
    assert artifact.is_source
    assert frozenset() == frozenset(artifact.parse_tags())

    artifact = Artifact.from_url(
        url="https://example.org/ansicolors-1.1.7-py2.py3-none-any.whl",
        fingerprint=Fingerprint(algorithm="sha1", hash="foo"),
    )
    assert isinstance(artifact, FileArtifact)
    assert "ansicolors-1.1.7-py2.py3-none-any.whl" == artifact.filename
    assert not artifact.is_source
    assert frozenset((Tag("py2", "none", "any"), Tag("py3", "none", "any"))) == frozenset(
        artifact.parse_tags()
    )


def test_vcs_artifact():
    # type: () -> None

    artifact = Artifact.from_url(
        url="git+https://github.com/pantsbuild/pex",
        fingerprint=Fingerprint(algorithm="md5", hash="bar"),
    )
    assert isinstance(artifact, VCSArtifact)
    assert VCS.Git is artifact.vcs
    assert artifact.is_source
    assert "pex @ git+https://github.com/pantsbuild/pex" == artifact.as_unparsed_requirement(
        ProjectName("pex")
    )

    artifact = Artifact.from_url(
        url="hg+https://github.com/pantsbuild/pex#egg=pex&subdirectory=.",
        fingerprint=Fingerprint(algorithm="sha1", hash="bar"),
    )
    assert isinstance(artifact, VCSArtifact)
    assert VCS.Mercurial is artifact.vcs
    assert artifact.is_source
    assert (
        "hg+https://github.com/pantsbuild/pex#egg=pex&subdirectory=."
        == artifact.as_unparsed_requirement(ProjectName("pex"))
    )
