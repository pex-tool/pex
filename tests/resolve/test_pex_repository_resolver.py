# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from collections import defaultdict

import pytest

from pex.common import safe_mkdtemp
from pex.interpreter import PythonInterpreter
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.platforms import Platform
from pex.resolve.pex_repository_resolver import resolve_from_pex
from pex.resolve.resolvers import Unsatisfiable
from pex.resolver import resolve
from pex.targets import Targets
from pex.testing import IS_LINUX, PY27, PY310, ensure_python_interpreter
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import DefaultDict, Iterable, Optional, Set


def create_pex_repository(
    interpreters=None,  # type: Optional[Iterable[PythonInterpreter]]
    platforms=None,  # type: Optional[Iterable[Platform]]
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    constraint_files=None,  # type: Optional[Iterable[str]]
    manylinux=None,  # type: Optional[str]
):
    # type: (...) -> str
    pex_builder = PEXBuilder()
    for installed_dist in resolve(
        targets=Targets(
            interpreters=tuple(interpreters) if interpreters else (),
            platforms=tuple(platforms) if platforms else (),
            assume_manylinux=manylinux,
        ),
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
    ).installed_distributions:
        pex_builder.add_distribution(installed_dist.distribution)
        for direct_req in installed_dist.direct_requirements:
            pex_builder.add_requirement(direct_req)
    pex_builder.freeze()
    return os.path.realpath(cast(str, pex_builder.path()))


def create_constraints_file(*requirements):
    # type: (*str) -> str
    constraints_file = os.path.join(safe_mkdtemp(), "constraints.txt")
    with open(constraints_file, "w") as fp:
        for requirement in requirements:
            fp.write(requirement + os.linesep)
    return constraints_file


@pytest.fixture(scope="module")
def py27():
    # type: () -> PythonInterpreter
    return PythonInterpreter.from_binary(ensure_python_interpreter(PY27))


@pytest.fixture(scope="module")
def py310():
    # type: () -> PythonInterpreter
    return PythonInterpreter.from_binary(ensure_python_interpreter(PY310))


@pytest.fixture(scope="module")
def macosx():
    # type: () -> Platform
    return Platform.create("macosx-10.13-x86_64-cp-36-m")


@pytest.fixture(scope="module")
def linux():
    # type: () -> Platform
    return Platform.create("linux-x86_64-cp-36-m")


@pytest.fixture(scope="module")
def manylinux():
    # type: () -> Optional[str]
    return None if IS_LINUX else "manylinux2014"


@pytest.fixture(scope="module")
def foreign_platform(
    macosx,  # type: Platform
    linux,  # type: Platform
):
    # type: (...) -> Platform
    return macosx if IS_LINUX else linux


@pytest.fixture(scope="module")
def pex_repository(py27, py310, foreign_platform, manylinux):
    # type () -> str

    # N.B.: requests 2.25.1 constrains urllib3 to <1.27,>=1.21.1 and pick 1.26.2 on its own as of
    # this writing.
    constraints_file = create_constraints_file("urllib3==1.26.1")

    return create_pex_repository(
        interpreters=[py27, py310],
        platforms=[foreign_platform],
        requirements=["requests[security,socks]==2.25.1"],
        constraint_files=[constraints_file],
        manylinux=manylinux,
    )


def test_resolve_from_pex(
    pex_repository,  # type: str
    py27,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
    foreign_platform,  # type: Platform
    manylinux,  # type: Optional[str]
):
    # type: (...) -> None
    pex_info = PexInfo.from_pex(pex_repository)
    direct_requirements = pex_info.requirements
    assert 1 == len(direct_requirements)

    result = resolve_from_pex(
        pex=pex_repository,
        requirements=direct_requirements,
        targets=Targets(
            interpreters=(py27, py310),
            platforms=(foreign_platform,),
            assume_manylinux=manylinux,
        ),
    )

    distribution_locations_by_key = defaultdict(set)  # type: DefaultDict[str, Set[str]]
    for installed_distribution in result.installed_distributions:
        distribution_locations_by_key[installed_distribution.distribution.key].add(
            installed_distribution.distribution.location
        )

    assert {
        os.path.basename(location)
        for locations in distribution_locations_by_key.values()
        for location in locations
    } == set(pex_info.distributions.keys()), (
        "Expected to resolve the same full set of distributions from the pex repository as make "
        "it up when using the same requirements."
    )

    assert "requests" in distribution_locations_by_key
    assert 1 == len(distribution_locations_by_key["requests"])

    assert "pysocks" in distribution_locations_by_key
    assert 2 == len(distribution_locations_by_key["pysocks"]), (
        "PySocks has a non-platform-specific Python 2.7 distribution and a non-platform-specific "
        "Python 3 distribution; so we expect to resolve two distributions - one covering "
        "Python 2.7 and one covering local Python 3.6 and our cp36 foreign platform."
    )

    assert "cryptography" in distribution_locations_by_key
    assert 3 == len(distribution_locations_by_key["cryptography"]), (
        "The cryptography requirement of the security extra is platform specific; so we expect a "
        "unique distribution to be resolved for each of the three distribution targets"
    )


def test_resolve_from_pex_subset(
    pex_repository,  # type: str
    foreign_platform,  # type: Platform
    manylinux,  # type: Optional[str]
):
    # type: (...) -> None

    result = resolve_from_pex(
        pex=pex_repository,
        requirements=["cffi"],
        targets=Targets(
            platforms=(foreign_platform,),
            assume_manylinux=manylinux,
        ),
    )

    assert {"cffi", "pycparser"} == {
        installed_distribution.distribution.key
        for installed_distribution in result.installed_distributions
    }


def test_resolve_from_pex_not_found(
    pex_repository,  # type: str
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    with pytest.raises(Unsatisfiable) as exec_info:
        resolve_from_pex(
            pex=pex_repository,
            requirements=["pex"],
            targets=Targets(
                interpreters=(py310,),
            ),
        )
    assert "A distribution for pex could not be resolved in this environment." in str(
        exec_info.value
    )

    with pytest.raises(Unsatisfiable) as exec_info:
        resolve_from_pex(
            pex=pex_repository,
            requirements=["requests==1.0.0"],
            targets=Targets(
                interpreters=(py310,),
            ),
        )
    message = str(exec_info.value)
    assert (
        "Failed to resolve requirements from PEX environment @ {}".format(pex_repository) in message
    )
    assert "Needed {} compatible dependencies for:".format(py310.platform.tag) in message
    assert "1: requests==1.0.0" in message
    assert "But this pex only contains:" in message
    assert "requests-2.25.1-py2.py3-none-any.whl" in message


def test_resolve_from_pex_intransitive(
    pex_repository,  # type: str
    py27,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
    foreign_platform,  # type: Platform
    manylinux,  # type: Optional[str]
):
    # type: (...) -> None

    installed_distributions = resolve_from_pex(
        pex=pex_repository,
        requirements=["requests"],
        transitive=False,
        targets=Targets(
            interpreters=(py27, py310),
            platforms=(foreign_platform,),
            assume_manylinux=manylinux,
        ),
    ).installed_distributions
    assert 3 == len(
        installed_distributions
    ), "Expected one resolved distribution per distribution target."
    assert 1 == len(
        frozenset(
            installed_distribution.distribution.location
            for installed_distribution in installed_distributions
        )
    ), (
        "Expected one underlying resolved universal distribution usable on Linux and macOs by "
        "both Python 2.7 and Python 3.6."
    )
    for installed_distribution in installed_distributions:
        assert (
            Requirement.parse("requests==2.25.1")
            == installed_distribution.distribution.as_requirement()
        )
        assert 1 == len(installed_distribution.direct_requirements)
        assert Requirement.parse("requests") == installed_distribution.direct_requirements[0]


def test_resolve_from_pex_constraints(
    pex_repository,  # type: str
    py27,  # type: PythonInterpreter
):
    # type: (...) -> None

    with pytest.raises(Unsatisfiable) as exec_info:
        resolve_from_pex(
            pex=pex_repository,
            requirements=["requests"],
            constraint_files=[create_constraints_file("urllib3==1.26.2")],
            targets=Targets(
                interpreters=(py27,),
            ),
        )
    message = str(exec_info.value)
    assert "The following constraints were not satisfied by " in message
    assert " resolved from {}:".format(pex_repository) in message
    assert "urllib3==1.26.2" in message


def test_resolve_from_pex_ignore_errors(
    pex_repository,  # type: str
    py27,  # type: PythonInterpreter
):
    # type: (...) -> None

    # See test_resolve_from_pex_constraints above for the failure this would otherwise cause.
    result = resolve_from_pex(
        pex=pex_repository,
        requirements=["requests"],
        constraint_files=[create_constraints_file("urllib3==1.26.2")],
        targets=Targets(
            interpreters=(py27,),
        ),
        ignore_errors=True,
    )
    installed_distributions_by_key = {
        installed_distribution.distribution.key: installed_distribution.distribution.as_requirement()
        for installed_distribution in result.installed_distributions
    }
    assert (
        len(installed_distributions_by_key) > 1
    ), "We should resolve at least requests and urllib3"
    assert "requests" in installed_distributions_by_key
    assert Requirement.parse("urllib3==1.26.1") == installed_distributions_by_key["urllib3"]
