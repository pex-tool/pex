# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import platform
import subprocess
from contextlib import contextmanager
from textwrap import dedent

import pytest

from pex import resolver
from pex.common import open_zip, temporary_dir
from pex.compatibility import PY2, nested, to_bytes
from pex.environment import PEXEnvironment
from pex.inherit_path import InheritPath
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.resolver import resolve
from pex.testing import (
    IS_LINUX,
    PY35,
    WheelBuilder,
    ensure_python_interpreter,
    make_bdist,
    temporary_content,
    temporary_filename,
)
from pex.third_party.pkg_resources import Distribution
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict, Iterable, Iterator, Optional, Tuple


@contextmanager
def yield_pex_builder(zip_safe=True, interpreter=None):
    # type: (bool, Optional[PythonInterpreter]) -> Iterator[PEXBuilder]
    with nested(temporary_dir(), make_bdist("p1", zip_safe=zip_safe, interpreter=interpreter)) as (
        td,
        p1,
    ):
        pb = PEXBuilder(path=td, interpreter=interpreter)
        pb.add_dist_location(p1.location)
        yield pb


def test_force_local():
    # type: () -> None
    with nested(yield_pex_builder(), temporary_dir(), temporary_filename()) as (
        pb,
        pex_root,
        pex_file,
    ):
        pb.info.pex_root = pex_root
        pb.build(pex_file)

        code_cache = PEXEnvironment._force_local(pex_file, pb.info)

        assert os.path.exists(pb.info.zip_unsafe_cache)
        listing = set(os.listdir(pb.info.zip_unsafe_cache))

        # The code_cache should be a write-locked directory.
        assert len(listing) == 2
        listing.remove(os.path.basename(code_cache))
        lockfile = listing.pop()
        assert os.path.isfile(os.path.join(pb.info.zip_unsafe_cache, lockfile))

        assert set(os.listdir(code_cache)) == {PexInfo.PATH, "__main__.py", "__main__.pyc"}

        # idempotence
        assert PEXEnvironment._force_local(pex_file, pb.info) == code_cache


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
        for resolved_dist in resolve(requirements, cache=cache, interpreter=builder.interpreter):
            builder.add_requirement(resolved_dist.requirement)
            builder.add_distribution(resolved_dist.distribution)

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

    with nested(temporary_dir(), temporary_dir()) as (root, cache):
        pex_info1 = PexInfo.default()
        pex_info1.zip_safe = False
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

        assert 42 == PEX(pex2, interpreter=interpreter).run(env=dict(PEX_VERBOSE="9"))


@pytest.fixture
def setuptools_requirement():
    # type: () -> str
    # We use a very old version of setuptools to prove the point the user version is what is used
    # here and not the vendored version (when possible). A newer setuptools is needed though to work
    # with python 3.
    return "setuptools==1.0" if PY2 else "setuptools==17.0"


def test_issues_598_explicit_any_interpreter(setuptools_requirement):
    # type: (str) -> None
    assert_force_local_implicit_ns_packages_issues_598(
        requirements=[setuptools_requirement], create_ns_packages=True
    )


def test_issues_598_explicit_missing_requirement():
    # type: () -> None
    assert_force_local_implicit_ns_packages_issues_598(create_ns_packages=True)


@pytest.fixture
def python_35_interpreter():
    # type: () -> PythonInterpreter
    # Python 3.5 supports implicit namespace packages.
    return PythonInterpreter.from_binary(ensure_python_interpreter(PY35))


def test_issues_598_implicit(python_35_interpreter):
    # type: (PythonInterpreter) -> None
    assert_force_local_implicit_ns_packages_issues_598(
        interpreter=python_35_interpreter, create_ns_packages=False
    )


def test_issues_598_implicit_explicit_mixed(python_35_interpreter, setuptools_requirement):
    # type: (PythonInterpreter, str) -> None
    assert_force_local_implicit_ns_packages_issues_598(
        interpreter=python_35_interpreter,
        requirements=[setuptools_requirement],
        create_ns_packages=True,
    )


def normalize(path):
    # type: (str) -> str
    return os.path.normpath(os.path.realpath(path)).lower()


def assert_dist_cache(zip_safe):
    # type: (bool) -> None
    with nested(yield_pex_builder(zip_safe=zip_safe), temporary_dir(), temporary_filename()) as (
        pb,
        pex_root,
        pex_file,
    ):

        pb.info.pex_root = pex_root
        pb.build(pex_file)

        with open_zip(pex_file) as zf:
            dists = PEXEnvironment._write_zipped_internal_cache(zf=zf, pex_info=pb.info)
            assert len(dists) == 1
            original_location = normalize(dists[0].location)
            assert original_location.startswith(normalize(pb.info.install_cache))

        # Call a second time to validate idempotence of caching.
        dists = PEXEnvironment._write_zipped_internal_cache(zf=None, pex_info=pb.info)
        assert len(dists) == 1
        assert normalize(dists[0].location) == original_location


def test_write_zipped_internal_cache():
    # type: () -> None
    assert_dist_cache(zip_safe=False)

    # Zip_safe pexes still always should have dists written to install cache, only the pex code (
    # sources and resources) should be imported from the pex zip when zip safe.
    assert_dist_cache(zip_safe=True)


def test_load_internal_cache_unzipped():
    # type: () -> None
    # Unzipped pexes should use distributions from the pex internal cache.
    with nested(yield_pex_builder(zip_safe=True), temporary_dir()) as (pb, pex_root):
        pb.info.pex_root = pex_root
        pb.freeze()

        dists = list(PEXEnvironment._load_internal_cache(pb.path(), pb.info))
        assert len(dists) == 1
        assert normalize(dists[0].location).startswith(
            normalize(os.path.join(pb.path(), pb.info.internal_cache))
        )


_KNOWN_BAD_APPLE_INTERPRETER = (
    "/System/Library/Frameworks/Python.framework/Versions/"
    "2.7/Resources/Python.app/Contents/MacOS/Python"
)


@pytest.mark.skipif(
    not os.path.exists(_KNOWN_BAD_APPLE_INTERPRETER),
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
        with nested(yield_pex_builder(interpreter=bad_interpreter()), temporary_filename()) as (
            pb,
            pex_file,
        ):
            for resolved_dist in resolver.resolve(
                ["psutil==5.4.3"], cache=cache, interpreter=pb.interpreter
            ):
                pb.add_dist_location(resolved_dist.distribution.location)
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
        for resolved_dist in resolver.resolve(["pex[requests]==1.6.3"], interpreter=pb.interpreter):
            pb.add_requirement(resolved_dist.requirement)
            pb.add_dist_location(resolved_dist.distribution.location)
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
    for resolved_dist in resolver.resolve([requirement]):
        pb.add_dist_location(resolved_dist.distribution.location)
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


@pytest.mark.parametrize(
    ("wheel_filename", "wheel_is_linux"),
    [
        pytest.param(
            "llvmlite-0.29.0-cp35-cp35m-linux_x86_64.whl", True, id="without_build_tag_linux"
        ),
        pytest.param(
            "llvmlite-0.29.0-1-cp35-cp35m-linux_x86_64.whl", True, id="with_build_tag_linux"
        ),
        pytest.param(
            "llvmlite-0.29.0-cp35-cp35m-macosx_10.9_x86_64.whl", False, id="without_build_tag_osx"
        ),
        pytest.param(
            "llvmlite-0.29.0-1-cp35-cp35m-macosx_10.9_x86_64.whl", False, id="with_build_tag_osx"
        ),
    ],
)
def test_can_add_handles_optional_build_tag_in_wheel(
    python_35_interpreter, wheel_filename, wheel_is_linux
):
    # type: (PythonInterpreter, str, bool) -> None
    pex_environment = PEXEnvironment(
        pex="", pex_info=PexInfo.default(python_35_interpreter), interpreter=python_35_interpreter
    )
    native_wheel = IS_LINUX and wheel_is_linux
    assert pex_environment.can_add(Distribution(wheel_filename)) is native_wheel


def test_can_add_handles_invalid_wheel_filename(python_35_interpreter):
    # type: (PythonInterpreter) -> None
    pex_environment = PEXEnvironment(
        pex="", pex_info=PexInfo.default(python_35_interpreter), interpreter=python_35_interpreter
    )
    assert pex_environment.can_add(Distribution("pep427-invalid.whl")) is False
