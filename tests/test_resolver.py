# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import os
import subprocess
from collections import defaultdict
from textwrap import dedent

import pkginfo
import pytest

from pex.common import safe_copy, safe_mkdtemp, temporary_dir
from pex.compatibility import nested
from pex.distribution_target import DistributionTarget
from pex.interpreter import PythonInterpreter, spawn_python_job
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.platforms import Platform
from pex.resolver import (
    InstalledDistribution,
    IntegrityError,
    LocalDistribution,
    Unsatisfiable,
    download,
    install,
    resolve_from_pex,
    resolve_multi,
)
from pex.testing import (
    IS_LINUX,
    IS_PYPY,
    PY27,
    PY35,
    PY36,
    PY_VER,
    built_wheel,
    ensure_python_interpreter,
    make_project,
    make_source_dir,
)
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, DefaultDict, Iterable, List, Optional, Set, Union


def create_sdist(**kwargs):
    # type: (**Any) -> str
    dist_dir = safe_mkdtemp()

    with make_project(**kwargs) as project_dir:
        cmd = ["setup.py", "sdist", "--dist-dir={}".format(dist_dir)]
        spawn_python_job(
            args=cmd,
            cwd=project_dir,
            expose=["setuptools"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).communicate()

    dists = os.listdir(dist_dir)
    assert len(dists) == 1
    return os.path.join(dist_dir, dists[0])


def build_wheel(**kwargs):
    # type: (**Any) -> str
    with built_wheel(**kwargs) as whl:
        return whl


def local_resolve_multi(*args, **kwargs):
    # type: (*Any, **Any) -> List[InstalledDistribution]
    # Skip remote lookups.
    kwargs["indexes"] = []
    return list(resolve_multi(*args, **kwargs))


def test_empty_resolve():
    # type: () -> None
    empty_resolve_multi = local_resolve_multi([])
    assert empty_resolve_multi == []

    with temporary_dir() as td:
        empty_resolve_multi = local_resolve_multi([], cache=td)
        assert empty_resolve_multi == []


def test_simple_local_resolve():
    # type: () -> None
    project_wheel = build_wheel(name="project")

    with temporary_dir() as td:
        safe_copy(project_wheel, os.path.join(td, os.path.basename(project_wheel)))
        resolved_dists = local_resolve_multi(["project"], find_links=[td])
        assert len(resolved_dists) == 1


def test_resolve_cache():
    # type: () -> None
    project_wheel = build_wheel(name="project")

    with nested(temporary_dir(), temporary_dir()) as (td, cache):
        safe_copy(project_wheel, os.path.join(td, os.path.basename(project_wheel)))

        # Without a cache, each resolve should be isolated, but otherwise identical.
        resolved_dists1 = local_resolve_multi(["project"], find_links=[td])
        resolved_dists2 = local_resolve_multi(["project"], find_links=[td])
        assert resolved_dists1 != resolved_dists2
        assert len(resolved_dists1) == 1
        assert len(resolved_dists2) == 1
        assert resolved_dists1[0].direct_requirement == resolved_dists2[0].direct_requirement
        assert resolved_dists1[0].distribution.location != resolved_dists2[0].distribution.location

        # With a cache, each resolve should be identical.
        resolved_dists3 = local_resolve_multi(["project"], find_links=[td], cache=cache)
        resolved_dists4 = local_resolve_multi(["project"], find_links=[td], cache=cache)
        assert resolved_dists1 != resolved_dists3
        assert resolved_dists2 != resolved_dists3
        assert resolved_dists3 == resolved_dists4


def test_diamond_local_resolve_cached():
    # type: () -> None
    # This exercises the issue described here: https://github.com/pantsbuild/pex/issues/120
    project1_wheel = build_wheel(name="project1", install_reqs=["project2<1.0.0"])
    project2_wheel = build_wheel(name="project2")

    with temporary_dir() as dd:
        for wheel in (project1_wheel, project2_wheel):
            safe_copy(wheel, os.path.join(dd, os.path.basename(wheel)))
        with temporary_dir() as cd:
            resolved_dists = local_resolve_multi(
                ["project1", "project2"], find_links=[dd], cache=cd
            )
            assert len(resolved_dists) == 2


def test_cached_dependency_pinned_unpinned_resolution_multi_run():
    # type: () -> None
    # This exercises the issue described here: https://github.com/pantsbuild/pex/issues/178
    project1_0_0 = build_wheel(name="project", version="1.0.0")
    project1_1_0 = build_wheel(name="project", version="1.1.0")

    with temporary_dir() as td:
        for wheel in (project1_0_0, project1_1_0):
            safe_copy(wheel, os.path.join(td, os.path.basename(wheel)))
        with temporary_dir() as cd:
            # First run, pinning 1.0.0 in the cache
            resolved_dists = local_resolve_multi(["project==1.0.0"], find_links=[td], cache=cd)
            assert len(resolved_dists) == 1
            assert resolved_dists[0].distribution.version == "1.0.0"

            # Second, run, the unbounded 'project' req will find the 1.0.0 in the cache. But should also
            # return SourcePackages found in td
            resolved_dists = local_resolve_multi(["project"], find_links=[td], cache=cd)
            assert len(resolved_dists) == 1
            assert resolved_dists[0].distribution.version == "1.1.0"


def test_intransitive():
    # type: () -> None
    foo1_0 = build_wheel(name="foo", version="1.0.0")
    # The nonexistent req ensures that we are actually not acting transitively (as that would fail).
    bar1_0 = build_wheel(name="bar", version="1.0.0", install_reqs=["nonexistent==1.0.0"])
    with temporary_dir() as td:
        for wheel in (foo1_0, bar1_0):
            safe_copy(wheel, os.path.join(td, os.path.basename(wheel)))
        with temporary_dir() as cd:
            resolved_dists = local_resolve_multi(
                ["foo", "bar"], find_links=[td], cache=cd, transitive=False
            )
            assert len(resolved_dists) == 2


def test_resolve_prereleases():
    # type: () -> None
    stable_dep = build_wheel(name="dep", version="2.0.0")
    prerelease_dep = build_wheel(name="dep", version="3.0.0rc3")

    with temporary_dir() as td:
        for wheel in (stable_dep, prerelease_dep):
            safe_copy(wheel, os.path.join(td, os.path.basename(wheel)))

        def assert_resolve(expected_version, **resolve_kwargs):
            resolved_dists = local_resolve_multi(["dep>=1,<4"], find_links=[td], **resolve_kwargs)
            assert 1 == len(resolved_dists)
            resolved_dist = resolved_dists[0]
            assert expected_version == resolved_dist.distribution.version

        assert_resolve("2.0.0")
        assert_resolve("2.0.0", allow_prereleases=False)
        assert_resolve("3.0.0rc3", allow_prereleases=True)


def _parse_requirement(req):
    # type: (Union[str, Requirement]) -> Requirement
    if isinstance(req, Requirement):
        req = str(req)
    return Requirement.parse(req)


def test_resolve_extra_setup_py():
    # type: () -> None
    with make_source_dir(
        name="project1", version="1.0.0", extras_require={"foo": ["project2"]}
    ) as project1_dir:
        project2_wheel = build_wheel(name="project2", version="2.0.0")
        with temporary_dir() as td:
            safe_copy(project2_wheel, os.path.join(td, os.path.basename(project2_wheel)))

            resolved_dists = local_resolve_multi(["{}[foo]".format(project1_dir)], find_links=[td])
            assert {_parse_requirement(req) for req in ("project1==1.0.0", "project2==2.0.0")} == {
                _parse_requirement(resolved_dist.distribution.as_requirement())
                for resolved_dist in resolved_dists
            }


def test_resolve_extra_wheel():
    # type: () -> None
    project1_wheel = build_wheel(
        name="project1", version="1.0.0", extras_require={"foo": ["project2"]}
    )
    project2_wheel = build_wheel(name="project2", version="2.0.0")
    with temporary_dir() as td:
        for wheel in (project1_wheel, project2_wheel):
            safe_copy(wheel, os.path.join(td, os.path.basename(wheel)))

        resolved_dists = local_resolve_multi(["project1[foo]"], find_links=[td])
        assert {_parse_requirement(req) for req in ("project1==1.0.0", "project2==2.0.0")} == {
            _parse_requirement(resolved_dist.distribution.as_requirement())
            for resolved_dist in resolved_dists
        }


def resolve_wheel_names(**kwargs):
    # type: (**Any) -> List[str]
    return [
        os.path.basename(resolved_distribution.distribution.location)
        for resolved_distribution in resolve_multi(**kwargs)
    ]


def resolve_p537_wheel_names(**kwargs):
    # type: (**Any) -> List[str]
    return resolve_wheel_names(requirements=["p537==1.0.4"], transitive=False, **kwargs)


@pytest.fixture(scope="module")
def p537_resolve_cache():
    # type: () -> str
    return safe_mkdtemp()


@pytest.mark.skipif(
    PY_VER < (3, 5) or IS_PYPY, reason="The p537 distribution only builds for CPython 3.5+"
)
def test_resolve_current_platform(p537_resolve_cache):
    # type: (str) -> None
    resolve_current = functools.partial(
        resolve_p537_wheel_names, cache=p537_resolve_cache, platforms=["current"]
    )

    other_python_version = PY36 if PY_VER == (3, 5) else PY35
    other_python = PythonInterpreter.from_binary(ensure_python_interpreter(other_python_version))
    current_python = PythonInterpreter.get()

    resolved_other = resolve_current(interpreters=[other_python])
    resolved_current = resolve_current()

    assert 1 == len(resolved_other)
    assert 1 == len(resolved_current)
    assert resolved_other != resolved_current
    assert resolved_current == resolve_current(interpreters=[current_python])
    assert resolved_current == resolve_current(interpreters=[current_python, current_python])

    # Here we have 2 local interpreters satisfying current but with different platforms and thus
    # different dists for 2 total dists.
    assert 2 == len(resolve_current(interpreters=[current_python, other_python]))


@pytest.mark.skipif(
    PY_VER < (3, 5) or IS_PYPY, reason="The p537 distribution only builds for CPython 3.5+"
)
def test_resolve_current_and_foreign_platforms(p537_resolve_cache):
    # type: (str) -> None
    foreign_platform = "macosx-10.13-x86_64-cp-37-m" if IS_LINUX else "manylinux1_x86_64-cp-37-m"
    resolve_current_and_foreign = functools.partial(
        resolve_p537_wheel_names, cache=p537_resolve_cache, platforms=["current", foreign_platform]
    )

    assert 2 == len(resolve_current_and_foreign())

    other_python_version = PY36 if PY_VER == (3, 5) else PY35
    other_python = PythonInterpreter.from_binary(ensure_python_interpreter(other_python_version))
    current_python = PythonInterpreter.get()

    assert 2 == len(resolve_current_and_foreign(interpreters=[current_python]))
    assert 2 == len(resolve_current_and_foreign(interpreters=[other_python]))
    assert 2 == len(resolve_current_and_foreign(interpreters=[current_python, current_python]))

    # Here we have 2 local interpreters, satisfying current, but with different platforms and thus
    # different dists and then the foreign platform for 3 total dists.
    assert 3 == len(resolve_current_and_foreign(interpreters=[current_python, other_python]))


def test_resolve_foreign_abi3():
    # type: () -> None
    # For version 2.8, cryptography publishes the following abi3 wheels for linux and macosx:
    # cryptography-2.8-cp34-abi3-macosx_10_6_intel.whl
    # cryptography-2.8-cp34-abi3-manylinux1_x86_64.whl
    # cryptography-2.8-cp34-abi3-manylinux2010_x86_64.whl

    cryptogrpahy_resolve_cache = safe_mkdtemp()
    foreign_ver = "37" if PY_VER == (3, 6) else "36"
    resolve_cryptography_wheel_names = functools.partial(
        resolve_wheel_names,
        requirements=["cryptography==2.8"],
        platforms=[
            "linux_x86_64-cp-{}-m".format(foreign_ver),
            "macosx_10.11_x86_64-cp-{}-m".format(foreign_ver),
        ],
        transitive=False,
        build=False,
        cache=cryptogrpahy_resolve_cache,
    )

    wheel_names = resolve_cryptography_wheel_names(manylinux="manylinux2014")
    assert {
        "cryptography-2.8-cp34-abi3-manylinux2010_x86_64.whl",
        "cryptography-2.8-cp34-abi3-macosx_10_6_intel.whl",
    } == set(wheel_names)

    wheel_names = resolve_cryptography_wheel_names(manylinux="manylinux2010")
    assert {
        "cryptography-2.8-cp34-abi3-manylinux2010_x86_64.whl",
        "cryptography-2.8-cp34-abi3-macosx_10_6_intel.whl",
    } == set(wheel_names)

    wheel_names = resolve_cryptography_wheel_names(manylinux="manylinux1")
    assert {
        "cryptography-2.8-cp34-abi3-manylinux1_x86_64.whl",
        "cryptography-2.8-cp34-abi3-macosx_10_6_intel.whl",
    } == set(wheel_names)


def test_issues_851():
    # type: () -> None
    # Previously, the PY36 resolve would fail post-resolution checks for configparser, pathlib2 and
    # contextlib2 which are only required for python_version<3.

    def resolve_pytest(python_version, pytest_version):
        interpreter = PythonInterpreter.from_binary(ensure_python_interpreter(python_version))
        resolved_dists = resolve_multi(
            interpreters=[interpreter], requirements=["pytest=={}".format(pytest_version)]
        )
        project_to_version = {rd.distribution.key: rd.distribution.version for rd in resolved_dists}
        assert project_to_version["pytest"] == pytest_version
        return project_to_version

    resolved_project_to_version = resolve_pytest(python_version=PY36, pytest_version="5.3.4")
    assert "importlib-metadata" in resolved_project_to_version
    assert "configparser" not in resolved_project_to_version
    assert "pathlib2" not in resolved_project_to_version
    assert "contextlib2" not in resolved_project_to_version

    resolved_project_to_version = resolve_pytest(python_version=PY27, pytest_version="4.6.9")
    assert "importlib-metadata" in resolved_project_to_version
    assert "configparser" in resolved_project_to_version
    assert "pathlib2" in resolved_project_to_version
    assert "contextlib2" in resolved_project_to_version


def test_issues_892():
    # type: () -> None
    python27 = ensure_python_interpreter(PY27)
    program = dedent(
        """\
        from __future__ import print_function

        import os
        import sys


        # This puts python3.6 stdlib on PYTHONPATH.
        os.environ['PYTHONPATH'] = os.pathsep.join(sys.path)


        from pex import resolver
        from pex.interpreter import PythonInterpreter


        python27 = PythonInterpreter.from_binary({python27!r})
        result = resolver.resolve(requirements=['packaging==19.2'], interpreter=python27)
        print('Resolved: {{}}'.format(result))
  """.format(
            python27=python27
        )
    )

    python36 = ensure_python_interpreter(PY36)
    cmd, process = PythonInterpreter.from_binary(python36).open_process(
        args=["-c", program], stderr=subprocess.PIPE
    )
    _, stderr = process.communicate()
    assert process.returncode == 0, dedent(
        """
        Command {cmd} failed with {returncode}.

        STDERR
        ======
        {stderr}
        """.format(
            cmd=cmd, returncode=process.returncode, stderr=stderr.decode("utf8")
        )
    )


def test_download():
    # type: () -> None
    project1_sdist = create_sdist(
        name="project1", version="1.0.0", extras_require={"foo": ["project2"]}
    )
    project2_wheel = build_wheel(
        name="project2",
        version="2.0.0",
        # This is the last version of setuptools compatible with Python 2.7.
        install_reqs=["setuptools==44.1.0"],
    )

    downloaded_by_target = defaultdict(list)
    for local_distribution in download(
        requirements=["{}[foo]".format(project1_sdist)],
        find_links=[os.path.dirname(project2_wheel)],
    ):
        distribution = pkginfo.get_metadata(local_distribution.path)
        downloaded_by_target[local_distribution.target].append(distribution)

    assert 1 == len(downloaded_by_target)

    target, distributions = downloaded_by_target.popitem()
    assert DistributionTarget.current() == target

    distributions_by_name = {distribution.name: distribution for distribution in distributions}
    assert 3 == len(distributions_by_name)

    def assert_dist(project_name, dist_type, version):
        dist = distributions_by_name[project_name]
        assert dist_type is type(dist)
        assert version == dist.version

    assert_dist("project1", pkginfo.SDist, "1.0.0")
    assert_dist("project2", pkginfo.Wheel, "2.0.0")
    assert_dist("setuptools", pkginfo.Wheel, "44.1.0")


def test_install():
    # type: () -> None
    project1_sdist = create_sdist(name="project1", version="1.0.0")
    project2_wheel = build_wheel(name="project2", version="2.0.0")

    installed_by_target = defaultdict(list)
    for installed_distribution in install(
        [LocalDistribution.create(path=dist) for dist in (project1_sdist, project2_wheel)]
    ):
        installed_by_target[installed_distribution.target].append(
            installed_distribution.distribution
        )

    assert 1 == len(installed_by_target)

    target, distributions = installed_by_target.popitem()
    assert DistributionTarget.current() == target

    distributions_by_name = {distribution.key: distribution for distribution in distributions}
    assert 2 == len(distributions_by_name)
    assert "1.0.0" == distributions_by_name["project1"].version
    assert "2.0.0" == distributions_by_name["project2"].version

    assert 2 == len(
        {distribution.location for distribution in distributions}
    ), "Expected installed distributions to have independent chroot paths."


def test_install_unsatisfiable():
    # type: () -> None
    project1_sdist = create_sdist(name="project1", version="1.0.0")
    project2_wheel = build_wheel(name="project2", version="2.0.0", install_reqs=["project1==1.0.1"])
    local_distributions = [
        LocalDistribution.create(path=dist) for dist in (project1_sdist, project2_wheel)
    ]

    assert 2 == len(install(local_distributions, ignore_errors=True))

    with pytest.raises(Unsatisfiable):
        install(local_distributions, ignore_errors=False)


def test_install_invalid_local_distribution():
    # type: () -> None
    project1_sdist = create_sdist(name="project1", version="1.0.0")

    valid_local_sdist = LocalDistribution.create(project1_sdist)
    assert 1 == len(install([valid_local_sdist]))

    with pytest.raises(IntegrityError):
        install([LocalDistribution.create(project1_sdist, fingerprint="mismatch")])

    project1_wheel = build_wheel(name="project1", version="1.0.0")
    with pytest.raises(IntegrityError):
        install(
            [LocalDistribution.create(project1_wheel, fingerprint=valid_local_sdist.fingerprint)]
        )


def test_resolve_arbitrary_equality_issues_940():
    # type: () -> None
    dist = create_sdist(
        name="foo",
        version="1.0.2-fba4511",
        python_requires=">=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*",
    )
    resolved_distributions = local_resolve_multi(
        requirements=[dist],
        # We need this to allow the invalid version above to sneak by pip wheel metadata
        # verification.
        verify_wheels=False,
    )

    assert len(resolved_distributions) == 1
    requirement = resolved_distributions[0].direct_requirement
    assert requirement is not None, (
        "The foo requirement was direct; so the resulting resolved distribution should carry the "
        "associated requirement."
    )
    assert [("===", "1.0.2-fba4511")] == requirement.specs
    assert requirement.marker is None


def test_resolve_overlapping_requirements_discriminated_by_markers_issues_1196(py27):
    # type: (PythonInterpreter) -> None
    resolved_distributions = resolve_multi(
        requirements=[
            "setuptools<45; python_full_version == '2.7.*'",
            "setuptools; python_version > '2.7'",
        ],
        interpreters=[py27],
    )
    assert 1 == len(resolved_distributions)
    resolved_distribution = resolved_distributions[0]
    assert (
        Requirement.parse("setuptools<45; python_full_version == '2.7.*'")
        == resolved_distribution.direct_requirement
    )
    assert (
        Requirement.parse("setuptools==44.1.1")
        == resolved_distribution.distribution.as_requirement()
    )


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
    for resolved_dist in resolve_multi(
        interpreters=interpreters,
        platforms=platforms,
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
        manylinux=manylinux,
    ):
        pex_builder.add_distribution(resolved_dist.distribution)
        if resolved_dist.direct_requirement:
            pex_builder.add_requirement(resolved_dist.direct_requirement)
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
def py36():
    # type: () -> PythonInterpreter
    return PythonInterpreter.from_binary(ensure_python_interpreter(PY36))


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
def pex_repository(py27, py36, foreign_platform, manylinux):
    # type () -> str

    # N.B.: requests 2.25.1 constrains urllib3 to <1.27,>=1.21.1 and pick 1.26.2 on its own as of
    # this writing.
    constraints_file = create_constraints_file("urllib3==1.26.1")

    return create_pex_repository(
        interpreters=[py27, py36],
        platforms=[foreign_platform],
        requirements=["requests[security,socks]==2.25.1"],
        constraint_files=[constraints_file],
        manylinux=manylinux,
    )


def test_resolve_from_pex(
    pex_repository,  # type: str
    py27,  # type: PythonInterpreter
    py36,  # type: PythonInterpreter
    foreign_platform,  # type: Platform
    manylinux,  # type: Optional[str]
):
    # type: (...) -> None
    pex_info = PexInfo.from_pex(pex_repository)
    direct_requirements = pex_info.requirements
    assert 1 == len(direct_requirements)

    resolved_distributions = resolve_from_pex(
        pex=pex_repository,
        requirements=direct_requirements,
        interpreters=[py27, py36],
        platforms=[foreign_platform],
        manylinux=manylinux,
    )

    distribution_locations_by_key = defaultdict(set)  # type: DefaultDict[str, Set[str]]
    for resolved_distribution in resolved_distributions:
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


def test_resolve_from_pex_subset(
    pex_repository,  # type: str
    foreign_platform,  # type: Platform
    manylinux,  # type: Optional[str]
):
    # type: (...) -> None

    resolved_distributions = resolve_from_pex(
        pex=pex_repository,
        requirements=["cffi"],
        platforms=[foreign_platform],
        manylinux=manylinux,
    )

    assert {"cffi", "pycparser"} == {
        resolved_distribution.distribution.key for resolved_distribution in resolved_distributions
    }


def test_resolve_from_pex_not_found(
    pex_repository,  # type: str
    py36,  # type: PythonInterpreter
):
    # type: (...) -> None

    with pytest.raises(Unsatisfiable) as exec_info:
        resolve_from_pex(
            pex=pex_repository,
            requirements=["pex"],
            interpreters=[py36],
        )
    assert "A distribution for pex could not be resolved in this environment." in str(
        exec_info.value
    )

    with pytest.raises(Unsatisfiable) as exec_info:
        resolve_from_pex(
            pex=pex_repository,
            requirements=["requests==1.0.0"],
            interpreters=[py36],
        )
    message = str(exec_info.value)
    assert (
        "Failed to resolve requirements from PEX environment @ {}".format(pex_repository) in message
    )
    assert "Needed {} compatible dependencies for:".format(py36.platform) in message
    assert "1: requests==1.0.0" in message
    assert "But this pex only contains:" in message
    assert "requests-2.25.1-py2.py3-none-any.whl" in message


def test_resolve_from_pex_intransitive(
    pex_repository,  # type: str
    py27,  # type: PythonInterpreter
    py36,  # type: PythonInterpreter
    foreign_platform,  # type: Platform
    manylinux,  # type: Optional[str]
):
    # type: (...) -> None

    resolved_distributions = resolve_from_pex(
        pex=pex_repository,
        requirements=["requests"],
        transitive=False,
        interpreters=[py27, py36],
        platforms=[foreign_platform],
        manylinux=manylinux,
    )
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
        assert Requirement.parse("requests") == resolved_distribution.direct_requirement


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
            interpreters=[py27],
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
    resolved_distributions = resolve_from_pex(
        pex=pex_repository,
        requirements=["requests"],
        constraint_files=[create_constraints_file("urllib3==1.26.2")],
        interpreters=[py27],
        ignore_errors=True,
    )
    resolved_distributions_by_key = {
        resolved_distribution.distribution.key: resolved_distribution.distribution.as_requirement()
        for resolved_distribution in resolved_distributions
    }
    assert len(resolved_distributions_by_key) > 1, "We should resolve at least requests and urllib3"
    assert "requests" in resolved_distributions_by_key
    assert Requirement.parse("urllib3==1.26.1") == resolved_distributions_by_key["urllib3"]
