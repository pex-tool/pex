# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import platform
import subprocess
from contextlib import contextmanager
from textwrap import dedent

import pytest

from pex import resolver
from pex.common import temporary_dir
from pex.compatibility import to_bytes
from pex.environment import PEXEnvironment, _InvalidWheelName, _RankedDistribution
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.inherit_path import InheritPath
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.rank import Rank
from pex.targets import LocalInterpreter, Targets
from pex.testing import (
    IS_LINUX,
    IS_PYPY3,
    PY37,
    WheelBuilder,
    ensure_python_interpreter,
    make_bdist,
    temporary_content,
    temporary_filename,
)
from pex.third_party.pkg_resources import Distribution
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Callable, Dict, Iterable, Iterator, Optional, Tuple


@contextmanager
def yield_pex_builder(zip_safe=True, interpreter=None):
    # type: (bool, Optional[PythonInterpreter]) -> Iterator[PEXBuilder]
    with temporary_dir() as td, make_bdist("p1", zip_safe=zip_safe, interpreter=interpreter) as p1:
        pb = PEXBuilder(path=td, interpreter=interpreter)
        pb.add_dist_location(p1.location)
        yield pb


def assert_force_local_implicit_ns_packages_issues_598(
    interpreter=None, requirements=(), create_ns_packages=True
):
    def create_foo_bar_setup(name, **extra_args):
        # type: (str, **Any) -> str
        setup_args = dict(name=name, version="0.0.1", packages=["foo", "foo.bar"])
        if create_ns_packages:
            setup_args.update(namespace_packages=["foo", "foo.bar"])
        if requirements:
            setup_args.update(install_requires=list(requirements))
        setup_args.update(extra_args)

        return dedent(
            """
            from setuptools import setup
            
            setup(**{setup_args!r})
            """.format(
                setup_args=setup_args
            )
        )

    def with_foo_bar_ns_packages(content):
        # type: (Dict[str, str]) -> Dict[str, str]
        ns_packages = (
            {
                os.path.join(
                    pkg, "__init__.py"
                ): '__import__("pkg_resources").declare_namespace(__name__)'
                for pkg in ("foo", "foo/bar")
            }
            if create_ns_packages
            else {}
        )
        ns_packages.update(content)
        return ns_packages

    content1 = with_foo_bar_ns_packages(
        {
            "foo/bar/spam.py": "identify = lambda: 42",
            "setup.py": create_foo_bar_setup("foo-bar-spam"),
        }
    )

    content2 = with_foo_bar_ns_packages(
        {
            "foo/bar/eggs.py": dedent(
                """
                # NB: This only works when this content is unpacked loose on the filesystem!
                def read_self():
                    with open(__file__) as fp:
                        return fp.read()
                """
            )
        }
    )

    content3 = with_foo_bar_ns_packages(
        {
            "foobaz": dedent(
                """\
                #!python
                import sys
                
                from foo.bar import baz
                
                sys.exit(baz.main())
                """
            ),
            "foo/bar/baz.py": dedent(
                """
                import sys
                
                from foo.bar import eggs, spam
                
                def main():
                    assert len(eggs.read_self()) > 0
                    return spam.identify()
                """
            ),
            "setup.py": create_foo_bar_setup("foo-bar-baz", scripts=["foobaz"]),
        }
    )

    def add_requirements(builder, cache):
        # type: (PEXBuilder, str) -> None
        for installed_dist in resolver.resolve(
            targets=Targets(interpreters=(builder.interpreter,)),
            requirements=requirements,
            cache=cache,
        ).installed_distributions:
            builder.add_distribution(installed_dist.distribution)
            for direct_req in installed_dist.direct_requirements:
                builder.add_requirement(direct_req)

    def add_wheel(builder, content):
        # type: (PEXBuilder, Dict[str, str]) -> None
        with temporary_content(content) as project:
            dist = WheelBuilder(project, interpreter=builder.interpreter).bdist()
            builder.add_dist_location(dist)

    def add_sources(builder, content):
        # type: (PEXBuilder, Dict[str, str]) -> None
        with temporary_content(content) as project:
            for path in content.keys():
                builder.add_source(os.path.join(project, path), path)

    with temporary_dir() as root, temporary_dir() as cache:
        pex_info1 = PexInfo.default()
        pex1 = os.path.join(root, "pex1.pex")
        builder1 = PEXBuilder(interpreter=interpreter, pex_info=pex_info1)
        add_requirements(builder1, cache)
        add_wheel(builder1, content1)
        add_sources(builder1, content2)
        builder1.build(pex1)

        pex_info2 = PexInfo.default()
        pex_info2.pex_path = pex1
        pex2 = os.path.join(root, "pex2")
        builder2 = PEXBuilder(path=pex2, interpreter=interpreter, pex_info=pex_info2)
        add_requirements(builder2, cache)
        add_wheel(builder2, content3)
        builder2.set_script("foobaz")
        builder2.freeze()

        assert 42 == PEX(pex2, interpreter=interpreter).run()


def get_setuptools_requirement(interpreter=None):
    # type: (Optional[PythonInterpreter]) -> str
    # We use a very old version of setuptools to prove the point the user version is what is used
    # here and not the vendored version (when possible). A newer setuptools is needed though to work
    # with python 3.
    return (
        "setuptools==1.0"
        if (interpreter or PythonInterpreter.get()).version[0] == 2
        else "setuptools==17.0"
    )


@pytest.mark.xfail(IS_PYPY3, reason="https://github.com/pantsbuild/pex/issues/1210")
def test_issues_598_explicit_any_interpreter():
    # type: () -> None
    assert_force_local_implicit_ns_packages_issues_598(
        requirements=[get_setuptools_requirement()], create_ns_packages=True
    )


def test_issues_598_explicit_missing_requirement():
    # type: () -> None
    assert_force_local_implicit_ns_packages_issues_598(create_ns_packages=True)


@pytest.fixture
def python_37_interpreter():
    # type: () -> PythonInterpreter
    # Python 3.7 supports implicit namespace packages.
    return PythonInterpreter.from_binary(ensure_python_interpreter(PY37))


def test_issues_598_implicit(python_37_interpreter):
    # type: (PythonInterpreter) -> None
    assert_force_local_implicit_ns_packages_issues_598(
        interpreter=python_37_interpreter, create_ns_packages=False
    )


def test_issues_598_implicit_explicit_mixed(python_37_interpreter):
    # type: (PythonInterpreter) -> None
    assert_force_local_implicit_ns_packages_issues_598(
        interpreter=python_37_interpreter,
        requirements=[get_setuptools_requirement(python_37_interpreter)],
        create_ns_packages=True,
    )


_KNOWN_BAD_APPLE_INTERPRETER = (
    "/System/Library/Frameworks/Python.framework/Versions/"
    "2.7/Resources/Python.app/Contents/MacOS/Python"
)


@pytest.mark.skipif(
    not os.path.exists(_KNOWN_BAD_APPLE_INTERPRETER)
    or subprocess.check_output(
        [
            _KNOWN_BAD_APPLE_INTERPRETER,
            "-c" "import sys; print('.'.join(map(str, sys.version_info[:3])))",
        ]
    )
    != b"2.7.10",
    reason="Test requires known bad Apple interpreter {}".format(_KNOWN_BAD_APPLE_INTERPRETER),
)
def test_osx_platform_intel_issue_523():
    # type: () -> None

    def bad_interpreter():
        # type: () -> PythonInterpreter
        return PythonInterpreter.from_binary(_KNOWN_BAD_APPLE_INTERPRETER)

    with temporary_dir() as cache:
        # We need to run the bad interpreter with a modern, non-Apple-Extras setuptools in order to
        # successfully install psutil; yield_pex_builder sets up the bad interpreter with our vendored
        # setuptools and wheel extras.
        with yield_pex_builder(
            interpreter=bad_interpreter()
        ) as pb, temporary_filename() as pex_file:
            for installed_dist in resolver.resolve(
                targets=Targets(interpreters=(pb.interpreter,)),
                requirements=["psutil==5.4.3"],
                cache=cache,
            ).installed_distributions:
                pb.add_dist_location(installed_dist.distribution.location)
            pb.build(pex_file)

            # NB: We want PEX to find the bare bad interpreter at runtime.
            pex = PEX(pex_file, interpreter=bad_interpreter())

            def run(args, **env):
                # type: (Iterable[str], **str) -> Tuple[int, str, str]
                pex_env = os.environ.copy()
                pex_env["PEX_VERBOSE"] = "1"
                pex_env.update(**env)
                process = pex.run(
                    args=args,
                    env=pex_env,
                    blocking=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                stdout, stderr = process.communicate()
                return process.returncode, stdout.decode("utf-8"), stderr.decode("utf-8")

            returncode, _, stderr = run(["-c", "import psutil"])
            assert 0 == returncode, "Process failed with exit code {} and stderr:\n{}".format(
                returncode, stderr
            )

            returncode, stdout, stderr = run(["-c", "import pkg_resources"])
            assert 0 != returncode, (
                "Isolated pex process succeeded but should not have found pkg-resources:\n"
                "STDOUT:\n"
                "{}\n"
                "STDERR:\n"
                "{}".format(stdout, stderr)
            )

            returncode, stdout, stderr = run(
                ["-c", "import pkg_resources; print(pkg_resources.get_supported_platform())"],
                # Let the bad interpreter site-packages setuptools leak in.
                PEX_INHERIT_PATH=InheritPath.for_value(True).value,
            )
            assert 0 == returncode, "Process failed with exit code {} and stderr:\n{}".format(
                returncode, stderr
            )

            # Verify this worked along side the previously problematic pkg_resources-reported platform.
            release, _, _ = platform.mac_ver()
            major_minor = ".".join(release.split(".")[:2])
            assert "macosx-{}-intel".format(major_minor) == stdout.strip()


def test_activate_extras_issue_615():
    # type: () -> None
    with yield_pex_builder() as pb:
        for installed_dist in resolver.resolve(
            targets=Targets(interpreters=(pb.interpreter,)),
            requirements=["pex[requests]==1.6.3"],
        ).installed_distributions:
            for direct_req in installed_dist.direct_requirements:
                pb.add_requirement(direct_req)
            pb.add_dist_location(installed_dist.distribution.location)
        pb.set_script("pex")
        pb.freeze()
        process = PEX(pb.path(), interpreter=pb.interpreter).run(
            args=["--version"],
            env={"PEX_VERBOSE": "9"},
            blocking=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate()
        assert 0 == process.returncode, "Process failed with exit code {} and output:\n{}".format(
            process.returncode, stderr
        )
        assert to_bytes("{} 1.6.3".format(os.path.basename(pb.path()))) == stdout.strip()


def assert_namespace_packages_warning(distribution, version, expected_warning):
    # type: (str, str, bool) -> None
    requirement = "{}=={}".format(distribution, version)
    pb = PEXBuilder()
    for installed_dist in resolver.resolve(requirements=[requirement]).installed_distributions:
        pb.add_dist_location(installed_dist.distribution.location)
    pb.freeze()

    process = PEX(pb.path()).run(args=["-c", ""], blocking=False, stderr=subprocess.PIPE)
    _, stderr = process.communicate()
    stderr_text = stderr.decode("utf8")

    partial_warning_preamble = "PEXWarning: The `pkg_resources` package was loaded"
    partial_warning_detail = "{} namespace packages:".format(requirement)

    if expected_warning:
        assert partial_warning_preamble in stderr_text
        assert partial_warning_detail in stderr_text
    else:
        assert partial_warning_preamble not in stderr_text
        assert partial_warning_detail not in stderr_text


def test_present_non_empty_namespace_packages_metadata_does_warn():
    # type: () -> None
    assert_namespace_packages_warning("twitter.common.lang", "0.3.11", expected_warning=True)


def test_present_but_empty_namespace_packages_metadata_does_not_warn():
    # type: () -> None
    assert_namespace_packages_warning("pycodestyle", "2.5.0", expected_warning=False)


def create_dist(
    location,  # type: str
    version="1.0.0",  # type: Optional[str]
):
    # type: (...) -> FingerprintedDistribution
    # N.B.: version must be set simply so that __hash__ / __eq__ work correctly in the
    # `pex.dist_metadata` module.
    return FingerprintedDistribution(
        distribution=Distribution(location=location, version=version), fingerprint=location
    )


@pytest.fixture
def cpython_37_environment(python_37_interpreter):
    return PEXEnvironment(
        pex="",
        pex_info=PexInfo.default(python_37_interpreter),
        target=LocalInterpreter.create(python_37_interpreter),
    )


@pytest.mark.parametrize(
    ("wheel_distribution", "wheel_is_linux"),
    [
        pytest.param(
            create_dist("llvmlite-0.29.0-cp37-cp37m-linux_x86_64.whl", "0.29.0"),
            True,
            id="without_build_tag_linux",
        ),
        pytest.param(
            create_dist("llvmlite-0.29.0-1-cp37-cp37m-linux_x86_64.whl", "0.29.0"),
            True,
            id="with_build_tag_linux",
        ),
        pytest.param(
            create_dist("llvmlite-0.29.0-cp37-cp37m-macosx_10.9_x86_64.whl", "0.29.0"),
            False,
            id="without_build_tag_osx",
        ),
        pytest.param(
            create_dist("llvmlite-0.29.0-1-cp37-cp37m-macosx_10.9_x86_64.whl", "0.29.0"),
            False,
            id="with_build_tag_osx",
        ),
    ],
)
def test_can_add_handles_optional_build_tag_in_wheel(
    cpython_37_environment, wheel_distribution, wheel_is_linux
):
    # type: (PEXEnvironment, FingerprintedDistribution, bool) -> None
    native_wheel = IS_LINUX and wheel_is_linux
    added = isinstance(cpython_37_environment._can_add(wheel_distribution), _RankedDistribution)
    assert added is native_wheel


def test_can_add_handles_invalid_wheel_filename(cpython_37_environment):
    # type: (PEXEnvironment) -> None
    dist = create_dist("pep427-invalid.whl")
    assert _InvalidWheelName(dist, "pep427-invalid") == cpython_37_environment._can_add(dist)


@pytest.fixture
def assert_cpython_37_environment_can_add(cpython_37_environment):
    # type: (PEXEnvironment) -> Callable[[FingerprintedDistribution], _RankedDistribution]
    def assert_can_add(dist):
        # type: (Distribution) -> _RankedDistribution
        rank = cpython_37_environment._can_add(dist)
        assert isinstance(rank, _RankedDistribution)
        return rank

    return assert_can_add


def test_can_add_ranking_platform_tag_more_specific(assert_cpython_37_environment_can_add):
    # type: (Callable[[Distribution], _RankedDistribution]) -> None
    ranked_specific = assert_cpython_37_environment_can_add(
        create_dist("foo-1.0.0-cp37-cp37m-macosx_10_9_x86_64.linux_x86_64.whl", "1.0.0")
    )
    ranked_universal = assert_cpython_37_environment_can_add(
        create_dist("foo-2.0.0-py2.py3-none-any.whl", "2.0.0")
    )
    assert ranked_specific < ranked_universal

    ranked_almost_py3universal = assert_cpython_37_environment_can_add(
        create_dist("foo-2.0.0-py3-none-any.whl", "2.0.0")
    )
    assert ranked_universal.rank == ranked_almost_py3universal.rank, (
        "Expected the 'universal' compressed tag set to be expanded into two tags and the more "
        "specific tag picked from those two for ranking."
    )


def test_can_add_ranking_version_newer_tie_break(assert_cpython_37_environment_can_add):
    # type: (Callable[[Distribution], _RankedDistribution]) -> None
    ranked_v1 = assert_cpython_37_environment_can_add(
        create_dist("foo-1.0.0-cp37-cp37m-macosx_10_9_x86_64.linux_x86_64.whl", "1.0.0")
    )
    ranked_v2 = assert_cpython_37_environment_can_add(
        create_dist("foo-2.0.0-cp37-cp37m-macosx_10_9_x86_64.linux_x86_64.whl", "2.0.0")
    )
    assert ranked_v2 < ranked_v1
