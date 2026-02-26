# Copyright 2015 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
import sys
import zipfile
from collections import defaultdict
from contextlib import contextmanager
from textwrap import dedent

import pytest

from pex import dist_metadata, targets
from pex.build_system.pep_517 import build_sdist
from pex.common import safe_copy, safe_mkdtemp, temporary_dir
from pex.dist_metadata import Distribution, Requirement
from pex.interpreter import PythonInterpreter
from pex.pep_427 import InstallableType
from pex.pip.version import PipVersion
from pex.resolve import abbreviated_platforms
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.package_repository import PYPI, Repo, ReposConfiguration
from pex.resolve.resolver_configuration import BuildConfiguration, ResolverVersion
from pex.resolve.resolvers import ResolvedDistribution, ResolveResult, Unsatisfiable
from pex.resolver import download
from pex.resolver import resolve as resolve_under_test
from pex.targets import Target, Targets
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from testing import (
    IS_LINUX,
    IS_PYPY,
    PY27,
    PY39,
    PY310,
    PY311,
    PY_VER,
    built_wheel,
    ensure_python_interpreter,
    make_project,
    make_source_dir,
    subprocess,
)
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Any, DefaultDict, Iterable, Iterator, List, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def create_sdist(**kwargs):
    # type: (**Any) -> str
    dist_dir = safe_mkdtemp()

    with make_project(**kwargs) as project_dir:
        build_sdist(
            project_directory=project_dir,
            dist_dir=dist_dir,
            target=targets.current(),
            resolver=ConfiguredResolver.default(),
        )

    dists = os.listdir(dist_dir)
    assert len(dists) == 1
    return os.path.join(dist_dir, dists[0])


def build_wheel(**kwargs):
    # type: (**Any) -> str
    with built_wheel(**kwargs) as whl:
        return whl


def resolve(**kwargs):
    # type: (**Any) -> ResolveResult
    kwargs.setdefault("resolver", ConfiguredResolver.default())
    return resolve_under_test(**kwargs)


def local_resolve(*args, **kwargs):
    # type: (*Any, **Any) -> List[ResolvedDistribution]
    # Skip remote lookups.
    repos_configuration = kwargs.pop("repos_configuration", ReposConfiguration())
    kwargs["repos_configuration"] = attr.evolve(repos_configuration, index_repos=())
    return list(resolve(*args, **kwargs).distributions)


@contextmanager
def cache(directory):
    # type: (str) -> Iterator[None]
    with ENV.patch(PEX_ROOT=directory):
        yield


@contextmanager
def disabled_cache():
    # type: () -> Iterator[None]

    # N.B.: The resolve cache is never actually disabled, `--disable-cache` just switches the cache
    # from default PEX_ROOT to a temporary directory. We do the same here.
    with temporary_dir() as td, cache(td):
        yield


def test_empty_resolve():
    # type: () -> None
    empty_resolve = local_resolve(requirements=[])
    assert empty_resolve == []

    with disabled_cache():
        empty_resolve = local_resolve(requirements=[])
        assert empty_resolve == []


def test_simple_local_resolve():
    # type: () -> None
    project_wheel = build_wheel(name="project")

    with temporary_dir() as td:
        safe_copy(project_wheel, os.path.join(td, os.path.basename(project_wheel)))
        resolved_dists = local_resolve(
            requirements=["project"],
            repos_configuration=ReposConfiguration.create(find_links=[Repo(td)]),
        )
        assert len(resolved_dists) == 1


def test_resolve_cache():
    # type: () -> None
    project_wheel = build_wheel(name="project")

    with temporary_dir() as td, temporary_dir() as cache_dir:
        safe_copy(project_wheel, os.path.join(td, os.path.basename(project_wheel)))

        # Without a cache, each resolve should be isolated, but otherwise identical.
        with disabled_cache():
            resolved_dists1 = local_resolve(
                requirements=["project"],
                repos_configuration=ReposConfiguration.create(find_links=[Repo(td)]),
            )
        with disabled_cache():
            resolved_dists2 = local_resolve(
                requirements=["project"],
                repos_configuration=ReposConfiguration.create(find_links=[Repo(td)]),
            )
        assert resolved_dists1 != resolved_dists2
        assert len(resolved_dists1) == 1
        assert len(resolved_dists2) == 1
        assert resolved_dists1[0].direct_requirements == resolved_dists2[0].direct_requirements
        assert resolved_dists1[0].distribution.location != resolved_dists2[0].distribution.location

        # With a cache, each resolve should be identical.
        with cache(cache_dir):
            resolved_dists3 = local_resolve(
                requirements=["project"],
                repos_configuration=ReposConfiguration.create(find_links=[Repo(td)]),
            )
            resolved_dists4 = local_resolve(
                requirements=["project"],
                repos_configuration=ReposConfiguration.create(find_links=[Repo(td)]),
            )
        assert resolved_dists1 != resolved_dists3
        assert resolved_dists2 != resolved_dists3
        assert resolved_dists3 == resolved_dists4


def test_diamond_local_resolve_cached():
    # type: () -> None
    # This exercises the issue described here: https://github.com/pex-tool/pex/issues/120
    project1_wheel = build_wheel(name="project1", install_reqs=["project2<1.0.0"])
    project2_wheel = build_wheel(name="project2")

    with temporary_dir() as dd:
        for wheel in (project1_wheel, project2_wheel):
            safe_copy(wheel, os.path.join(dd, os.path.basename(wheel)))
        with temporary_dir() as cd, cache(cd):
            resolved_dists = local_resolve(
                requirements=["project1", "project2"],
                repos_configuration=ReposConfiguration.create(find_links=[Repo(dd)]),
            )
            assert len(resolved_dists) == 2


def test_cached_dependency_pinned_unpinned_resolution_multi_run():
    # type: () -> None
    # This exercises the issue described here: https://github.com/pex-tool/pex/issues/178
    project1_0_0 = build_wheel(name="project", version="1.0.0")
    project1_1_0 = build_wheel(name="project", version="1.1.0")

    with temporary_dir() as td:
        for wheel in (project1_0_0, project1_1_0):
            safe_copy(wheel, os.path.join(td, os.path.basename(wheel)))
        with temporary_dir() as cd, cache(cd):
            # First run, pinning 1.0.0 in the cache
            resolved_dists = local_resolve(
                requirements=["project==1.0.0"],
                repos_configuration=ReposConfiguration.create(find_links=[Repo(td)]),
            )
            assert len(resolved_dists) == 1
            assert resolved_dists[0].distribution.version == "1.0.0"

            # Second, run, the unbounded 'project' req will find the 1.0.0 in the cache. But should
            # also return SourcePackages found in td
            resolved_dists = local_resolve(
                requirements=["project"],
                repos_configuration=ReposConfiguration.create(find_links=[Repo(td)]),
            )
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
        with temporary_dir() as cd, cache(cd):
            resolved_dists = local_resolve(
                requirements=["foo", "bar"],
                repos_configuration=ReposConfiguration.create(find_links=[Repo(td)]),
                transitive=False,
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
            resolved_dists = local_resolve(
                requirements=["dep>=1,<4"],
                repos_configuration=ReposConfiguration.create(find_links=[Repo(td)]),
                **resolve_kwargs
            )
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


def test_resolve_extra_setup_py(tmpdir):
    # type: (Tempdir) -> None
    with make_source_dir(
        name="project1", version="1.0.0", extras_require={"foo": ["project2"]}
    ) as project1_dir:
        project2_wheel = build_wheel(name="project2", version="2.0.0")
        safe_copy(project2_wheel, tmpdir.join(os.path.basename(project2_wheel)))
        result = resolve(
            requirements=["setuptools"],
            build_configuration=BuildConfiguration.create(allow_builds=False),
            result_type=InstallableType.WHEEL_FILE,
        )
        for resolved_dist in result.distributions:
            safe_copy(
                resolved_dist.distribution.location,
                tmpdir.join(os.path.basename(resolved_dist.distribution.location)),
            )

        resolved_dists = local_resolve(
            requirements=["{}[foo]".format(project1_dir)],
            repos_configuration=ReposConfiguration.create(find_links=[Repo(tmpdir.path)]),
        )
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

        resolved_dists = local_resolve(
            requirements=["project1[foo]"],
            repos_configuration=ReposConfiguration.create(find_links=[Repo(td)]),
        )
        assert {_parse_requirement(req) for req in ("project1==1.0.0", "project2==2.0.0")} == {
            _parse_requirement(resolved_dist.distribution.as_requirement())
            for resolved_dist in resolved_dists
        }


def resolve_wheel_names(**kwargs):
    # type: (**Any) -> List[str]
    return [
        os.path.basename(resolved_distribution.distribution.location)
        for resolved_distribution in resolve(**kwargs).distributions
    ]


def resolve_p537_wheel_names(
    cache_dir,  # type: str
    **kwargs  # type: Any
):
    # type: (...) -> List[str]
    with cache(cache_dir):
        return resolve_wheel_names(
            requirements=[
                "p537=={version}".format(
                    version="1.0.10" if sys.version_info[:2] >= (3, 6) else "1.0.5"
                )
            ],
            transitive=False,
            **kwargs
        )


@pytest.fixture(scope="module")
def p537_resolve_cache():
    # type: () -> str
    return safe_mkdtemp()


@pytest.mark.skipif(
    PY_VER < (3, 5) or IS_PYPY, reason="The p537 distribution only builds for CPython 3.5+"
)
def test_resolve_current_platform(p537_resolve_cache):
    # type: (str) -> None
    def resolve_current(interpreters=()):
        # type: (Iterable[PythonInterpreter]) -> List[str]

        # N.B.: None stands in for the "current" platform at higher layers that parse platform
        # strings to Platform objects.
        current_platform = (None,)
        return resolve_p537_wheel_names(
            cache_dir=p537_resolve_cache,
            targets=Targets(platforms=current_platform, interpreters=tuple(interpreters)),
        )

    other_python_version = PY311 if PY_VER == (3, 9) else PY39
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
    foreign_platform = "macosx-13.0-x86_64-cp-37-m" if IS_LINUX else "manylinux1_x86_64-cp-37-m"

    def resolve_current_and_foreign(interpreters=()):
        # type: (Iterable[PythonInterpreter]) -> List[str]

        # N.B.: None stands in for the "current" platform at higher layers that parse platform
        # strings to Platform objects.
        platforms = (None, abbreviated_platforms.create(foreign_platform))
        return resolve_p537_wheel_names(
            cache_dir=p537_resolve_cache,
            targets=Targets(platforms=platforms, interpreters=tuple(interpreters)),
        )

    assert 2 == len(resolve_current_and_foreign())

    other_python_version = PY311 if PY_VER == (3, 9) else PY39
    other_python = PythonInterpreter.from_binary(ensure_python_interpreter(other_python_version))
    current_python = PythonInterpreter.get()

    assert 2 == len(resolve_current_and_foreign(interpreters=[current_python]))
    assert 2 == len(resolve_current_and_foreign(interpreters=[other_python]))
    assert 2 == len(resolve_current_and_foreign(interpreters=[current_python, current_python]))

    # Here we have 2 local interpreters, satisfying current, but with different platforms and thus
    # different dists and then the foreign platform for 3 total dists.
    assert 3 == len(resolve_current_and_foreign(interpreters=[current_python, other_python]))


def test_resolve_foreign_abi3(tmpdir):
    # type: (Any) -> None
    # For version 2.8, cryptography publishes the following abi3 wheels for linux and macosx:
    # cryptography-2.8-cp34-abi3-macosx_10_6_intel.whl
    # cryptography-2.8-cp34-abi3-manylinux1_x86_64.whl
    # cryptography-2.8-cp34-abi3-manylinux2010_x86_64.whl

    cryptogrpahy_resolve_cache = os.path.join(str(tmpdir), "pex_root")
    foreign_ver = "37" if PY_VER == (3, 6) else "36"

    def resolve_cryptography_wheel_names(manylinux):
        with cache(cryptogrpahy_resolve_cache):
            return resolve_wheel_names(
                requirements=["cryptography==2.8"],
                targets=Targets(
                    platforms=(
                        abbreviated_platforms.create(
                            "linux_x86_64-cp-{}-m".format(foreign_ver), manylinux=manylinux
                        ),
                        abbreviated_platforms.create(
                            "macosx_10.11_x86_64-cp-{}-m".format(foreign_ver), manylinux=manylinux
                        ),
                    ),
                ),
                transitive=False,
                build_configuration=BuildConfiguration.create(allow_builds=False),
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
    # Previously, the PY38 resolve would fail post-resolution checks for importlib-metadata,
    # configparser, pathlib2 and contextlib2 which are only required for python_version<3.

    def resolve_pytest(python, pytest_version):
        interpreter = PythonInterpreter.from_binary(python)
        result = resolve(
            targets=Targets(interpreters=(interpreter,)),
            requirements=["pytest=={}".format(pytest_version)],
        )
        project_to_version = {
            resolved_dist.distribution.project_name: resolved_dist.distribution.version
            for resolved_dist in result.distributions
        }
        assert project_to_version["pytest"] == pytest_version
        return project_to_version

    resolved_project_to_version = resolve_pytest(
        python=ensure_python_interpreter(PY39), pytest_version="5.3.4"
    )
    assert "importlib-metadata" not in resolved_project_to_version
    assert "configparser" not in resolved_project_to_version
    assert "pathlib2" not in resolved_project_to_version
    assert "contextlib2" not in resolved_project_to_version

    resolved_project_to_version = resolve_pytest(
        python=ensure_python_interpreter(PY27), pytest_version="4.6.9"
    )
    assert "importlib-metadata" in resolved_project_to_version
    assert "configparser" in resolved_project_to_version
    assert "pathlib2" in resolved_project_to_version
    assert "contextlib2" in resolved_project_to_version


def test_issues_892(pex_project_dir):
    # type: (str) -> None
    python27 = ensure_python_interpreter(PY27)
    program = dedent(
        """\
        from __future__ import print_function

        import os
        import sys


        # This puts python3.10 stdlib on PYTHONPATH.
        os.environ['PYTHONPATH'] = os.pathsep.join(sys.path)

        sys.path.append({pex_project_dir!r})
        from pex import resolver
        from pex.interpreter import PythonInterpreter
        from pex.targets import Targets


        python27 = PythonInterpreter.from_binary({python27!r})
        result = resolver.resolve(
            targets=Targets(interpreters=(python27,)),
            requirements=['packaging==19.2'],
        )
        print('Resolved: {{}}'.format(result))
        """
    ).format(pex_project_dir=pex_project_dir, python27=python27)

    python310 = ensure_python_interpreter(PY310)
    cmd, process = PythonInterpreter.from_binary(python310).open_process(
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


def test_download2():
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

    downloaded_by_target = defaultdict(list)  # type: DefaultDict[Target, List[Distribution]]
    result = download(
        requirements=["{}[foo]".format(project1_sdist)],
        repos_configuration=ReposConfiguration.create(
            indexes=[Repo(PYPI)], find_links=[Repo(os.path.dirname(project2_wheel))]
        ),
        resolver=ConfiguredResolver.default(),
    )
    for local_distribution in result.local_distributions:
        distribution = Distribution.load(local_distribution.path)
        downloaded_by_target[local_distribution.target].append(distribution)

    assert 1 == len(downloaded_by_target)

    target, distributions = downloaded_by_target.popitem()
    assert targets.current() == target

    distributions_by_name = {
        distribution.project_name: distribution for distribution in distributions
    }
    assert 3 == len(distributions_by_name)

    def assert_dist(
        project_name,  # type: str
        version,  # type: str
        is_wheel,  # type: bool
    ):
        # type: (...) -> None

        dist = distributions_by_name[project_name]
        assert version == dist.version
        assert is_wheel == (
            dist_metadata.is_wheel(dist.location) and zipfile.is_zipfile(dist.location)
        )

    assert_dist("project1", "1.0.0", is_wheel=False)
    assert_dist("project2", "2.0.0", is_wheel=True)
    assert_dist("setuptools", "44.1.0", is_wheel=True)


@pytest.mark.skipif(
    sys.version_info[:2] >= (3, 12) or PipVersion.DEFAULT >= PipVersion.v24_1,
    reason=(
        "We need to use setuptools<66, but Python 3.12+ require greater. We also need to avoid "
        "Pip>=24.1 which upgrades its vendored packaging to a version that rejects invalid "
        "versions"
    ),
)
def test_resolve_arbitrary_equality_issues_940():
    # type: (...) -> None

    def prepare_project(project_dir):
        # type: (str) -> None
        with open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
            fp.write(
                dedent(
                    """\
                    [build-system]
                    # Setuptools 66 removed support for PEP-440 non-compliant versions.
                    # See: https://setuptools.pypa.io/en/stable/history.html#v66-0-0
                    requires = ["setuptools<66"]
                    """
                )
            )

    dist = create_sdist(
        prepare_project=prepare_project,
        name="foo",
        version="1.0.2-fba4511",
        python_requires=">=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*",
    )
    resolved_distributions = resolve(
        requirements=[dist],
        # We need this to allow the invalid version above to sneak by pip wheel metadata
        # verification.
        verify_wheels=False,
    ).distributions

    assert len(resolved_distributions) == 1
    requirements = resolved_distributions[0].direct_requirements
    assert 1 == len(requirements), (
        "The foo requirement was direct; so the resulting resolved distribution should carry the "
        "associated requirement."
    )
    assert "===1.0.2-fba4511" == str(requirements[0].specifier)
    assert requirements[0].marker is None


def test_resolve_overlapping_requirements_discriminated_by_markers_issues_1196(py27):
    # type: (PythonInterpreter) -> None
    resolved_distributions = resolve(
        requirements=[
            "setuptools<45; python_full_version == '2.7.*'",
            "setuptools; python_version > '2.7'",
        ],
        targets=Targets(
            interpreters=(py27,),
        ),
    ).distributions
    assert 1 == len(resolved_distributions)
    resolved_distribution = resolved_distributions[0]
    assert 1 == len(resolved_distribution.direct_requirements)
    assert (
        Requirement.parse("setuptools<45; python_full_version == '2.7.*'")
        == resolved_distribution.direct_requirements[0]
    )
    assert (
        Requirement.parse("setuptools==44.1.1")
        == resolved_distribution.distribution.as_requirement()
    )


def test_pip_proprietary_url_with_markers_issues_1415():
    # type: () -> None
    resolved_dists = resolve(
        requirements=[
            (
                "https://files.pythonhosted.org/packages/53/18/"
                "a56e2fe47b259bb52201093a3a9d4a32014f9d85071ad07e9d60600890ca/"
                "ansicolors-1.1.8-py2.py3-none-any.whl; sys_platform != '{}'".format(sys.platform)
            ),
            "ansicolors==1.1.8; sys_platform == '{}'".format(sys.platform),
        ]
    ).distributions
    assert len(resolved_dists) == 1

    resolved_dist = resolved_dists[0]
    assert Requirement.parse("ansicolors==1.1.8") == resolved_dist.distribution.as_requirement()
    assert 1 == len(resolved_dist.direct_requirements)
    assert (
        Requirement.parse("ansicolors==1.1.8; sys_platform == '{}'".format(sys.platform))
        == resolved_dist.direct_requirements[0]
    )


def test_duplicate_requirements_issues_1550():
    # type: () -> None

    with pytest.raises(Unsatisfiable):
        resolve(requirements=["PyJWT", "PyJWT==1.7.1"], resolver_version=ResolverVersion.PIP_LEGACY)

    resolved_dists = resolve(
        requirements=["PyJWT", "PyJWT==1.7.1"], resolver_version=ResolverVersion.PIP_2020
    )
    assert len(resolved_dists.distributions) == 1
    resolved_distribution = resolved_dists.distributions[0]
    assert {Requirement.parse("PyJWT"), Requirement.parse("PyJWT==1.7.1")} == set(
        resolved_distribution.direct_requirements
    )
    distribution = resolved_distribution.distribution
    assert "PyJWT" == distribution.project_name
    assert "1.7.1" == distribution.version


def test_check_resolve_prerelease_transitive_dependencies_issue_1730(tmpdir):
    # type: (Any) -> None

    indirect_wheel = build_wheel(name="indirect", version="2.12.0.dev3")
    direct_wheel = build_wheel(
        name="direct", version="2.12.0.dev3", install_reqs=["indirect==2.12.0.dev3"]
    )

    find_links = os.path.join(str(tmpdir), "find-links")
    os.mkdir(find_links)
    for wheel in direct_wheel, indirect_wheel:
        shutil.move(wheel, find_links)

    resolved = resolve(
        requirements=["direct==2.12.dev3"],
        allow_prereleases=False,
        ignore_errors=False,
        repos_configuration=ReposConfiguration.create(indexes=[], find_links=[Repo(find_links)]),
    )
    assert 2 == len(resolved.distributions)
