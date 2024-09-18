# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
from collections import defaultdict

import pytest

from pex.common import safe_mkdtemp
from pex.dist_metadata import DistributionType, Requirement
from pex.interpreter import PythonInterpreter
from pex.pep_427 import InstallableType
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.platforms import Platform
from pex.resolve import abbreviated_platforms
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.pex_repository_resolver import resolve_from_pex
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolve.resolvers import ResolveResult, Unsatisfiable
from pex.resolver import resolve
from pex.targets import Targets
from pex.typing import TYPE_CHECKING, cast
from testing import IS_LINUX, PY27, PY310, ensure_python_interpreter

if TYPE_CHECKING:
    from typing import DefaultDict, Iterable, Optional, Set


def create_pex_repository(
    interpreters=None,  # type: Optional[Iterable[PythonInterpreter]]
    platforms=None,  # type: Optional[Iterable[Platform]]
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    constraint_files=None,  # type: Optional[Iterable[str]]
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
):
    # type: (...) -> str
    pex_builder = PEXBuilder()
    pex_builder.info.deps_are_wheel_files = result_type is InstallableType.WHEEL_FILE
    for resolved_dist in resolve(
        targets=Targets(
            interpreters=tuple(interpreters) if interpreters else (),
            platforms=tuple(platforms) if platforms else (),
        ),
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
        resolver=ConfiguredResolver(PipConfiguration()),
        result_type=result_type,
    ).distributions:
        pex_builder.add_distribution(resolved_dist.distribution)
        for direct_req in resolved_dist.direct_requirements:
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
    return abbreviated_platforms.create("macosx-10.13-x86_64-cp-36-m")


@pytest.fixture(scope="module")
def linux():
    # type: () -> Platform
    return abbreviated_platforms.create("linux-x86_64-cp-36-m", manylinux="manylinux2014")


@pytest.fixture(scope="module")
def foreign_platform(
    macosx,  # type: Platform
    linux,  # type: Platform
):
    # type: (...) -> Platform
    return macosx if IS_LINUX else linux


@pytest.fixture(
    scope="module",
    params=[
        pytest.param(installable_type, id=installable_type.value)
        for installable_type in InstallableType.values()
    ],
)
def pex_repository(
    py27,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
    foreign_platform,  # type: Platform
    request,  # type: pytest.FixtureRequest
):
    # type (...) -> str

    constraints_file = create_constraints_file(
        # The 2.25.1 release of requests constrains urllib3 to <1.27,>=1.21.1 and picks 1.26.2 on
        # its own as of this writing.
        "urllib3==1.26.1",
        # The 22.0.0 release of pyOpenSSL drops support for Python 2.7; so we pin lower.
        "pyOpenSSL<22",
        # The 2022 and later releases only support Python>=3.6; so we pin lower.
        "certifi<2022",
        # The 2.22 release of pycparser drops support for Python 2.7.
        "pycparser<2.22",
    )

    return create_pex_repository(
        interpreters=[py27, py310],
        platforms=[foreign_platform],
        requirements=["requests[security,socks]==2.25.1"],
        constraint_files=[constraints_file],
        result_type=request.param,
    )


def test_resolve_from_pex(
    pex_repository,  # type: str
    py27,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
    foreign_platform,  # type: Platform
):
    # type: (...) -> None
    pex_info = PexInfo.from_pex(pex_repository)
    direct_requirements = pex_info.requirements
    assert 1 == len(direct_requirements)

    def assert_resolve_result(
        result,  # type: ResolveResult
        expected_result_type,  # type: InstallableType.Value
    ):
        # type: (...) -> None

        assert expected_result_type is result.type
        expected_dist_type = (
            DistributionType.WHEEL
            if expected_result_type is InstallableType.WHEEL_FILE
            else DistributionType.INSTALLED
        )

        distribution_locations_by_key = defaultdict(set)  # type: DefaultDict[str, Set[str]]
        for resolved_distribution in result.distributions:
            assert expected_dist_type is resolved_distribution.distribution.type
            distribution_locations_by_key[resolved_distribution.distribution.key].add(
                resolved_distribution.distribution.location
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

    assert_resolve_result(
        resolve_from_pex(
            pex=pex_repository,
            requirements=direct_requirements,
            targets=Targets(interpreters=(py27, py310), platforms=(foreign_platform,)),
        ),
        expected_result_type=InstallableType.INSTALLED_WHEEL_CHROOT,
    )

    if pex_info.deps_are_wheel_files:
        assert_resolve_result(
            resolve_from_pex(
                pex=pex_repository,
                requirements=direct_requirements,
                targets=Targets(interpreters=(py27, py310), platforms=(foreign_platform,)),
                result_type=InstallableType.WHEEL_FILE,
            ),
            expected_result_type=InstallableType.WHEEL_FILE,
        )
    else:
        with pytest.raises(
            Unsatisfiable,
            match=(
                r"Cannot resolve \.whl files from PEX at {pex}; its dependencies are in the form "
                r"of pre-installed wheel chroots\.".format(pex=re.escape(pex_repository))
            ),
        ):
            resolve_from_pex(
                pex=pex_repository,
                requirements=direct_requirements,
                targets=Targets(interpreters=(py27, py310), platforms=(foreign_platform,)),
                result_type=InstallableType.WHEEL_FILE,
            )


def test_resolve_from_pex_subset(
    pex_repository,  # type: str
    foreign_platform,  # type: Platform
):
    # type: (...) -> None

    result = resolve_from_pex(
        pex=pex_repository,
        requirements=["cffi"],
        targets=Targets(platforms=(foreign_platform,)),
    )

    assert {"cffi", "pycparser"} == {
        resolved_distribution.distribution.project_name
        for resolved_distribution in result.distributions
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
            targets=Targets(interpreters=(py310,)),
        )
    assert "A distribution for pex could not be resolved for {py310_exe}.".format(
        py310_exe=py310.binary
    ) in str(exec_info.value)

    with pytest.raises(Unsatisfiable) as exec_info:
        resolve_from_pex(
            pex=pex_repository,
            requirements=["requests==1.0.0"],
            targets=Targets(interpreters=(py310,)),
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
):
    # type: (...) -> None

    resolved_distributions = resolve_from_pex(
        pex=pex_repository,
        requirements=["requests"],
        transitive=False,
        targets=Targets(interpreters=(py27, py310), platforms=(foreign_platform,)),
    ).distributions
    assert 3 == len(
        resolved_distributions
    ), "Expected one resolved distribution per distribution target."
    assert 1 == len(
        frozenset(
            resolved_distribution.distribution.location
            for resolved_distribution in resolved_distributions
        )
    ), (
        "Expected one underlying resolved universal distribution usable on Linux and macOs by "
        "both Python 2.7 and Python 3.6."
    )
    for resolved_distribution in resolved_distributions:
        assert (
            Requirement.parse("requests==2.25.1")
            == resolved_distribution.distribution.as_requirement()
        )
        assert 1 == len(resolved_distribution.direct_requirements)
        assert Requirement.parse("requests") == resolved_distribution.direct_requirements[0]


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
            targets=Targets(interpreters=(py27,)),
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
        targets=Targets(interpreters=(py27,)),
        ignore_errors=True,
    )
    resolved_distributions_by_key = {
        resolved_distribution.distribution.project_name: resolved_distribution.distribution.as_requirement()
        for resolved_distribution in result.distributions
    }
    assert len(resolved_distributions_by_key) > 1, "We should resolve at least requests and urllib3"
    assert "requests" in resolved_distributions_by_key
    assert Requirement.parse("urllib3==1.26.1") == resolved_distributions_by_key["urllib3"]
