# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import filecmp
import itertools
import os.path
import platform
import re
import subprocess
import sys
from textwrap import dedent
from typing import Any, Dict, Iterator, Text

import pytest

import testing
from pex import targets, toml
from pex.atomic_directory import atomic_directory
from pex.common import CopyMode, iter_copytree, safe_copy
from pex.compatibility import string
from pex.interpreter import PythonInterpreter
from pex.os import WINDOWS
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.resolve.lockfile.pep_751 import Pylock
from pex.resolve.resolved_requirement import Pin
from pex.result import try_
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from pex.wheel import Wheel
from testing import IS_PYPY, IntegResults, data, make_env, run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from packaging.specifiers import SpecifierSet  # vendor:skip
else:
    from pex.third_party.packaging.specifiers import SpecifierSet


@pytest.fixture
def devpi_server_lock():
    # type: () -> str
    return data.path("locks", "devpi-server.lock.json")


def assert_valid_toml(value):
    # type: (Text) -> Dict[str, Any]

    table = toml.loads(value)
    assert isinstance(table, dict)
    assert all(isinstance(key, string) for key in table)
    return table


def test_universal_export_subset(devpi_server_lock):
    # type: (str) -> None

    result = run_pex3(
        "lock",
        "export-subset",
        "zope-deprecation",
        "--format",
        "pep-751",
        "--lock",
        devpi_server_lock,
    )
    result.assert_success()

    assert {
        "lock-version": "1.0",
        "environments": ["platform_system == 'Darwin'", "platform_system == 'Linux'"],
        "requires-python": "<3.14,>=3.10",
        "extras": [],
        "dependency-groups": [],
        "default-groups": [],
        "created-by": "pex",
        "packages": [
            {
                "name": "setuptools",
                "requires-python": ">=3.8",
                "version": "74.1.2",
                "sdist": {
                    "name": "setuptools-74.1.2.tar.gz",
                    "url": "https://files.pythonhosted.org/packages/3e/2c/f0a538a2f91ce633a78daaeb34cbfb93a54bd2132a6de1f6cec028eee6ef/setuptools-74.1.2.tar.gz",
                    "hashes": {
                        "sha256": "95b40ed940a1c67eb70fc099094bd6e99c6ee7c23aa2306f4d2697ba7916f9c6"
                    },
                },
                "wheels": [
                    {
                        "name": "setuptools-74.1.2-py3-none-any.whl",
                        "url": "https://files.pythonhosted.org/packages/cb/9c/9ad11ac06b97e55ada655f8a6bea9d1d3f06e120b178cd578d80e558191d/setuptools-74.1.2-py3-none-any.whl",
                        "hashes": {
                            "sha256": "5f4c08aa4d3ebcb57a50c33b1b07e94315d7fc7230f7115e47fc99776c8ce308"
                        },
                    }
                ],
            },
            {
                "name": "zope-deprecation",
                "requires-python": ">=3.7",
                "version": "5",
                "dependencies": [
                    {"name": "setuptools"},
                ],
                "sdist": {
                    "name": "zope.deprecation-5.0.tar.gz",
                    "url": "https://files.pythonhosted.org/packages/ba/de/a47e434ed1804d82f3fd7561aee5c55914c72d87f54cac6b99c15cbe7f89/zope.deprecation-5.0.tar.gz",
                    "hashes": {
                        "sha256": "b7c32d3392036b2145c40b3103e7322db68662ab09b7267afe1532a9d93f640f"
                    },
                },
                "wheels": [
                    {
                        "name": "zope.deprecation-5.0-py3-none-any.whl",
                        "url": "https://files.pythonhosted.org/packages/c8/7d/24a23d4d6d93744babfb99266eeb97a25ceae58c0f841a872b51c45ee214/zope.deprecation-5.0-py3-none-any.whl",
                        "hashes": {
                            "sha256": "28c2ee983812efb4676d33c7a8c6ade0df191c1c6d652bbbfe6e2eeee067b2d4"
                        },
                    },
                ],
            },
        ],
    } == assert_valid_toml(result.output)


def test_universal_export_subset_no_dependency_info(devpi_server_lock):
    # type: (str) -> None

    result = run_pex3(
        "lock",
        "export-subset",
        "zope-deprecation",
        "--format",
        "pep-751",
        "--no-include-dependency-info",
        "--lock",
        devpi_server_lock,
    )
    result.assert_success()

    assert {
        "lock-version": "1.0",
        "environments": ["platform_system == 'Darwin'", "platform_system == 'Linux'"],
        "requires-python": "<3.14,>=3.10",
        "extras": [],
        "dependency-groups": [],
        "default-groups": [],
        "created-by": "pex",
        "packages": [
            {
                "name": "setuptools",
                "requires-python": ">=3.8",
                "version": "74.1.2",
                "sdist": {
                    "name": "setuptools-74.1.2.tar.gz",
                    "url": "https://files.pythonhosted.org/packages/3e/2c/f0a538a2f91ce633a78daaeb34cbfb93a54bd2132a6de1f6cec028eee6ef/setuptools-74.1.2.tar.gz",
                    "hashes": {
                        "sha256": "95b40ed940a1c67eb70fc099094bd6e99c6ee7c23aa2306f4d2697ba7916f9c6"
                    },
                },
                "wheels": [
                    {
                        "name": "setuptools-74.1.2-py3-none-any.whl",
                        "url": "https://files.pythonhosted.org/packages/cb/9c/9ad11ac06b97e55ada655f8a6bea9d1d3f06e120b178cd578d80e558191d/setuptools-74.1.2-py3-none-any.whl",
                        "hashes": {
                            "sha256": "5f4c08aa4d3ebcb57a50c33b1b07e94315d7fc7230f7115e47fc99776c8ce308"
                        },
                    }
                ],
            },
            {
                "name": "zope-deprecation",
                "requires-python": ">=3.7",
                "version": "5",
                "sdist": {
                    "name": "zope.deprecation-5.0.tar.gz",
                    "url": "https://files.pythonhosted.org/packages/ba/de/a47e434ed1804d82f3fd7561aee5c55914c72d87f54cac6b99c15cbe7f89/zope.deprecation-5.0.tar.gz",
                    "hashes": {
                        "sha256": "b7c32d3392036b2145c40b3103e7322db68662ab09b7267afe1532a9d93f640f"
                    },
                },
                "wheels": [
                    {
                        "name": "zope.deprecation-5.0-py3-none-any.whl",
                        "url": "https://files.pythonhosted.org/packages/c8/7d/24a23d4d6d93744babfb99266eeb97a25ceae58c0f841a872b51c45ee214/zope.deprecation-5.0-py3-none-any.whl",
                        "hashes": {
                            "sha256": "28c2ee983812efb4676d33c7a8c6ade0df191c1c6d652bbbfe6e2eeee067b2d4"
                        },
                    },
                ],
            },
        ],
    } == assert_valid_toml(result.output)


def pin(
    project_name,  # type: str
    version,  # type: str
):
    # type: (...) -> Pin
    return Pin(project_name=ProjectName(project_name), version=Version(version))


def iter_expected_devpi_server_deps():
    # type: () -> Iterator[Pin]

    yield pin("anyio", "4.4.0")
    yield pin("argon2-cffi", "23.1.0")
    yield pin("argon2-cffi-bindings", "21.2.0")
    yield pin("attrs", "24.2.0")
    yield pin("certifi", "2024.8.30")
    yield pin("cffi", "1.17.1")
    yield pin("charset-normalizer", "3.3.2")
    yield pin("defusedxml", "0.7.1")
    yield pin("devpi-common", "4.0.4")
    yield pin("devpi-server", "6.12.1")

    if sys.version_info[:2] < (3, 11):
        yield pin("exceptiongroup", "1.2.2")

    yield pin("h11", "0.14.0")
    yield pin("httpcore", "1.0.5")
    yield pin("httpx", "0.27.2")
    yield pin("hupper", "1.12.1")
    yield pin("idna", "3.8")
    yield pin("itsdangerous", "2.2.0")
    yield pin("lazy", "1.6")

    if sys.version_info[:2] >= (3, 13):
        yield pin("legacy-cgi", "2.6.1")

    yield pin("packaging", "24.1")
    yield pin("packaging-legacy", "23.0.post0")
    yield pin("passlib", "1.7.4")
    yield pin("pastedeploy", "3.1.0")
    yield pin("plaster", "1.1.2")
    yield pin("plaster-pastedeploy", "1.0.1")
    yield pin("platformdirs", "4.3.2")
    yield pin("pluggy", "1.5.0")
    yield pin("py", "1.11.0")
    yield pin("pycparser", "2.22")
    yield pin("pyramid", "2.0.2")
    yield pin("python-dateutil", "2.9.0.post0")
    yield pin("repoze-lru", "0.7")
    yield pin("requests", "2.32.3")
    yield pin("ruamel-yaml", "0.18.6")

    if not IS_PYPY and sys.version_info[:2] < (3, 13):
        yield pin("ruamel-yaml-clib", "0.2.8")

    yield pin("setuptools", "74.1.2")
    yield pin("six", "1.16.0")
    yield pin("sniffio", "1.3.1")
    yield pin("strictyaml", "1.7.3")
    yield pin("translationstring", "1.4")

    if sys.version_info[:2] < (3, 11):
        yield pin("typing-extensions", "4.12.2")

    yield pin("urllib3", "2.2.3")
    yield pin("venusian", "3.1.0")
    yield pin("waitress", "3.0.0")
    yield pin("webob", "1.8.8")
    yield pin("zope-deprecation", "5.0")
    yield pin("zope-interface", "7.0.3")


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 10), reason="The lock under test requires Python >= 3.10."
)
def test_universal_export_interop(
    tmpdir,  # type: Tempdir
    devpi_server_lock,  # type: str
):
    # type: (...) -> None

    pylock_toml = tmpdir.join("pylock.toml")
    result = run_pex3(
        "lock",
        "export",
        "--format",
        "pep-751",
        # N.B.: As of this writing, uv does not support dependencies being filled out:
        #  https://github.com/astral-sh/uv/issues/13383
        # TODO(John Sirois): Drop this when we bump to a required uv version floor that fixes this.
        "--no-include-dependency-info",
        "-o",
        pylock_toml,
        devpi_server_lock,
    )
    result.assert_success()

    assert_valid_toml(result.output)

    venv_dir = tmpdir.join("venv")
    venv = Virtualenv.create(venv_dir=venv_dir)
    assert [] == list(venv.iter_distributions())

    current_interpreter = PythonInterpreter.get()
    python = "{impl}{version}".format(
        impl="pypy" if current_interpreter.is_pypy else "python", version=current_interpreter.python
    )
    subprocess.check_call(
        args=["uv", "pip", "install", "--python", python, "-r", pylock_toml, "--prefix", venv_dir]
    )
    sort_by_pin = lambda pin: (pin.project_name.normalized, pin.version.normalized)
    assert sorted(iter_expected_devpi_server_deps(), key=sort_by_pin) == sorted(
        (
            Pin(dist.metadata.project_name, dist.metadata.version)
            for dist in venv.iter_distributions(rescan=True)
        ),
        key=sort_by_pin,
    )


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 8),
    reason="Building Pex requires Python >= 3.8 to read pyproject.toml heterogeneous arrays.",
)
def test_lock_all_package_types(
    tmpdir,  # type: Tempdir
    pex_project_dir,  # type: str
    pex_wheel,  # type: str
):
    # type: (...) -> None

    requirements = tmpdir.join("requirements.txt")
    with open(requirements, "w") as fp:
        fp.write(
            dedent(
                """\
                # Stress the editable bit for directory packages.
                -e {pex_project_dir}
                
                # Stress extras handling, sdists and wheels.
                requests[socks]
                
                # Stress archive handling.
                PySocks @ git+https://github.com/Anorov/PySocks@1.7.0
                
                # Stress VCS handling.
                cowsay @ https://github.com/VaasuDevanS/cowsay-python/archive/dcf7236f0b5ece9ed56e91271486e560526049cf.zip
                """.format(
                    pex_project_dir=pex_project_dir
                )
            )
        )
    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--pip-version",
        "latest-compatible",
        "--style",
        "sources",
        "-r",
        requirements,
        "--indent",
        "2",
        "-o",
        lock,
        "-v",
    ).assert_success()

    result = run_pex3("lock", "export", "--format", "pep-751", lock)
    result.assert_success()

    pylock_toml = assert_valid_toml(result.output)
    packages_by_name = {package["name"]: package for package in pylock_toml["packages"]}

    assert {
        "name": "pex",
        "requires-python": str(Wheel.load(pex_wheel).dist_metadata().requires_python),
        "directory": {
            "path": pex_project_dir,
            "editable": True,
        },
    } == packages_by_name["pex"]

    requests_pkg = packages_by_name["requests"]
    assert {"name": "pysocks"} in requests_pkg["dependencies"]
    assert "sdist" in requests_pkg
    assert len(requests_pkg["wheels"]) > 0

    assert {
        "name": "pysocks",
        "requires-python": "!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,>=2.7",
        "version": "1.7",
        "vcs": {
            "type": "git",
            "url": "https://github.com/Anorov/PySocks",
            "requested-revision": "1.7.0",
            "commit-id": "91dcdf0fec424b6afe9ceef88de63b72d2f8fcfe",
        },
    } == packages_by_name["pysocks"]

    assert {
        "name": "cowsay",
        "requires-python": ">=3.8",
        "version": "6.1",
        "archive": {
            "url": "https://github.com/VaasuDevanS/cowsay-python/archive/dcf7236f0b5ece9ed56e91271486e560526049cf.zip",
            "hashes": {
                "sha256": "27dc8a9f155ed95045cbacb5f5990b80d6bb32193e818b8ab8b09f883a6b7096",
            },
        },
    } == packages_by_name["cowsay"]


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 8),
    reason="Building Pex requires Python >= 3.8 to read pyproject.toml heterogeneous arrays.",
)
def test_locks_equivalent_round_trip(
    tmpdir,  # type: Tempdir
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    pex_management_req = "{pex_project_dir}[management]".format(pex_project_dir=pex_project_dir)

    requirements = tmpdir.join("requirements.txt")
    with open(requirements, "w") as fp:
        fp.write(
            dedent(
                """\
                # Stress the editable bit for directory packages as well as handling extras.
                -e {pex_management_req}

                # Stress archive subdirectory handling.
                git+https://github.com/SerialDev/sdev_py_utils.git@bd4d36a0#egg=sdev_logging_utils&subdirectory=sdev_logging_utils

                # Stress VCS subdirectory handling as well as sdists and wheels (insta-science has
                # a fair number of transitive deps).
                insta-science @ https://github.com/a-scie/science-installers/archive/refs/tags/python-v0.6.1.zip#subdirectory=python
                """.format(
                    pex_management_req=pex_management_req
                )
            )
        )
    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--pip-version",
        "latest-compatible",
        "--style",
        "sources",
        "-r",
        requirements,
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()

    pylock_toml = tmpdir.join("pylock.toml")
    run_pex3("lock", "export", "--format", "pep-751", lock, "-o", pylock_toml).assert_success()

    lock_pex_full = tmpdir.join("lock.pex")
    pylock_pex_full = tmpdir.join("pylock.pex")
    lock_pex_subset = tmpdir.join("lock.subset.pex")
    pylock_pex_subset = tmpdir.join("pylock.subset.pex")

    lock_full_args = ["--pip-version", "latest-compatible"]
    lock_subset_args = lock_full_args + [pex_management_req]
    results = [
        run_pex_command(args=lock_full_args + ["--lock", lock, "-o", lock_pex_full]),
        run_pex_command(args=lock_full_args + ["--pylock", pylock_toml, "-o", pylock_pex_full]),
        run_pex_command(args=lock_subset_args + ["--lock", lock, "-o", lock_pex_subset]),
        run_pex_command(args=lock_subset_args + ["--pylock", pylock_toml, "-o", pylock_pex_subset]),
    ]
    for result in results:
        result.assert_success()

    filecmp.cmp(lock_pex_full, pylock_pex_full, shallow=False)
    filecmp.cmp(lock_pex_subset, pylock_pex_subset, shallow=False)

    assert {ProjectName("pex"), ProjectName("psutil")} == {
        dist.metadata.project_name for dist in PEX(pylock_pex_subset).resolve()
    }, (
        "Expected extras in root requirements to be respected throughout the lock, export and PEX "
        "build chain of custody."
    )


def pex_pylock_applicable():
    # type: () -> bool

    if sys.version_info[:2] < (3, 8):
        return False

    # PyPy can't track the early return above vs the possibility the test is run under, say
    # Python 2.7.
    pex_pyproject_data = toml.load(  # type: ignore[unreachable]
        os.path.join(testing.pex_project_dir(), "pyproject.toml")
    )
    pex_requires_python = pex_pyproject_data["project"]["requires-python"]
    return platform.python_version() in SpecifierSet(pex_requires_python)


@pytest.mark.skipif(
    not pex_pylock_applicable(),
    reason=(
        "Building Pex requires Python >= 3.8 to read pyproject.toml heterogeneous arrays and this"
        "test also needs the current interpreter to work with production PEX (be within its "
        "Requires-Python upper bounds) since its the production PEX Requires-Python that will be "
        "seen by the PEX's `uv.lock`."
    ),
)
def test_uv_pylock_interop(
    tmpdir,  # type: Tempdir
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    chroot = tmpdir.join("chroot")
    list(
        itertools.chain.from_iterable(
            (
                iter_copytree(
                    src=os.path.join(pex_project_dir, "build-backend"),
                    dst=os.path.join(chroot, "build-backend"),
                    copy_mode=CopyMode.LINK if WINDOWS else CopyMode.SYMLINK,
                ),
                iter_copytree(
                    src=os.path.join(pex_project_dir, "pex"),
                    dst=os.path.join(chroot, "pex"),
                    copy_mode=CopyMode.LINK if WINDOWS else CopyMode.SYMLINK,
                ),
            )
        )
    )
    for file in "MANIFEST.in", "pyproject.toml", "setup.cfg", "setup.py", "uv.lock":
        safe_copy(os.path.join(pex_project_dir, file), os.path.join(chroot, file))

    pylock_toml = os.path.join(chroot, "pylock.toml")
    subprocess.check_call(
        args=[
            "uv",
            "export",
            "--directory",
            chroot,
            "--no-dev",
            "--extra",
            "management",
            "--format",
            "pylock.toml",
            "-q",
            "-o",
            pylock_toml,
        ]
    )

    management_pex = tmpdir.join("management.pex")
    run_pex_command(
        args=[
            ".[management]",
            "--pylock",
            pylock_toml,
            "--pip-version",
            "latest-compatible",
            "-o",
            management_pex,
        ],
        cwd=chroot,
        quiet=True,
    ).assert_failure(
        expected_error_re=r"^{escaped}$".format(
            escaped=re.escape(
                "The following projects were resolved:\n"
                "+ pex\n"
                "\n"
                "These additional dependencies need to be resolved (as well as any transitive "
                "dependencies they may have):\n"
                "+ psutil\n"
                "\n"
                "The lock {pylock} created by uv likely does not include optional `dependencies` "
                "metadata for its packages.\n"
                "This metadata is required for Pex to subset a PEP-751 lock.".format(
                    pylock=pylock_toml
                )
            )
        )
    )

    run_pex_command(
        args=["--pylock", pylock_toml, "--pip-version", "latest-compatible", "-o", management_pex]
    ).assert_success()
    assert {ProjectName("pex"), ProjectName("psutil")} == {
        dist.metadata.project_name for dist in PEX(management_pex).resolve()
    }


@pytest.fixture(scope="session")
def pdm_exported_pylock_toml(shared_integration_test_tmpdir):
    # type: (str) -> str

    lock_dir = os.path.join(shared_integration_test_tmpdir, "test_pep_751_pdm_exported")
    with atomic_directory(lock_dir) as chroot:
        if not chroot.is_finalized():
            with open(os.path.join(chroot.work_dir, "pyproject.toml"), "w") as fp:
                fp.write(
                    dedent(
                        """\
                        [project]
                        name = "fake"
                        version = "1"
                        requires-python = ">=3.9"
                        dependencies = ["cowsay<6"]

                        [project.optional-dependencies]
                        pytest = ["pytest"]

                        [dependency-groups]
                        tox = ["tox"]
                        """
                    )
                )

            def run_pdm(*args):
                # type: (*str) -> None
                subprocess.check_call(
                    args=["uv", "tool", "run", "--from", "pdm>=2.24.2", "pdm"] + list(args),
                    cwd=chroot.work_dir,
                    env=make_env(PDM_USE_VENV="False"),
                )

            run_pdm("lock", "-d", "-G", ":all")
            run_pdm("export", "-f", "pylock", "-o", "pylock.toml")
    return os.path.join(lock_dir, "pylock.toml")


def assert_pdm_less_than_39_failure(
    result,  # type: IntegResults
    pdm_exported_pylock_toml,  # type: str
):
    # type: (...) -> None

    assert sys.version_info[:2] <= (3, 9)

    if sys.version_info[:2] == (3, 8):
        result.assert_failure(
            expected_error_re="^{exact}$".format(
                exact=re.escape(
                    "Failed to resolve compatible artifacts from lock {pylock} created by pdm for "
                    "1 target:\n"
                    "1. {target}: This lock only works in limited environments, none of which "
                    "support the current target.\n"
                    "The supported environments are:\n"
                    '+ python_version >= "3.9"\n'.format(
                        pylock=pdm_exported_pylock_toml, target=targets.current()
                    )
                )
            )
        )
        return

    result.assert_failure(
        expected_error_re=(
            r"^Failed to parse the PEP-751 lock at {pylock}. Error parsing content at "
            r"packages\[\d.+\n"
            r"Failed to parse marker .+\n"
            r"It appears this marker uses `extras` or `dependency_groups` which are only "
            r"supported for Python 3.8 or newer.\n$".format(pylock=pdm_exported_pylock_toml)
        ),
        re_flags=re.DOTALL | re.MULTILINE,
    )


def test_pdm_extras_interop(
    pdm_exported_pylock_toml,  # type: str
    tmpdir,  # type: Tempdir
):
    # type: (...) -> None

    pytest_pex = tmpdir.join("pytest.pex")
    result = run_pex_command(
        args=[
            "--pylock",
            pdm_exported_pylock_toml,
            "--pylock-extra",
            "pytest",
            "-c",
            "pytest",
            "-o",
            pytest_pex,
        ],
        quiet=True,
    )
    if sys.version_info[:2] < (3, 9):
        assert_pdm_less_than_39_failure(result, pdm_exported_pylock_toml)
    else:
        result.assert_success()

        pylock = try_(Pylock.parse(pdm_exported_pylock_toml))
        packages_by_project_name = {package.project_name: package for package in pylock.packages}
        pytest_version = packages_by_project_name[ProjectName("pytest")].version
        assert pytest_version is not None

        assert (
            "pytest {version}".format(version=pytest_version.raw)
            == subprocess.check_output(args=[pytest_pex, "-V"]).decode("utf-8").strip()
        )

        # N.B.: This both tests that without activating the pytest extra, we don't get pytest and
        # that default-groups are applied, which is what are used here.
        cowsay_version = packages_by_project_name[ProjectName("cowsay")].version
        assert cowsay_version is not None

        cowsay_pex = tmpdir.join("cowsay.pex")
        run_pex_command(
            args=["--pylock", pdm_exported_pylock_toml, "-c", "cowsay", "-o", cowsay_pex]
        ).assert_success()

        assert ProjectName("pytest") not in {
            dist.metadata.project_name for dist in PEX(cowsay_pex).resolve()
        }
        assert cowsay_version == Version(
            subprocess.check_output(args=[cowsay_pex, "--version"]).decode("utf-8").strip()
        )


def test_pdm_dependency_groups_interop(
    pdm_exported_pylock_toml,  # type: str
    tmpdir,  # type: Tempdir
):
    # type: (...) -> None

    tox_pex = tmpdir.join("tox.pex")
    result = run_pex_command(
        args=[
            "--pylock",
            pdm_exported_pylock_toml,
            "--pylock-group",
            "tox",
            "--pylock-group",
            "default",
            "-c",
            "tox",
            "-o",
            tox_pex,
        ],
        quiet=True,
    )
    if sys.version_info[:2] < (3, 9):
        assert_pdm_less_than_39_failure(result, pdm_exported_pylock_toml)
    else:
        result.assert_success()

        pylock = try_(Pylock.parse(pdm_exported_pylock_toml))
        packages_by_project_name = {package.project_name: package for package in pylock.packages}
        tox_version = packages_by_project_name[ProjectName("tox")].version
        assert tox_version is not None

        # Pre PI-stabilization, tox fails to run under Python 3.14 with:
        #   File ".../tox/config/cli/parser.py", line 277, in add_argument
        #     result = super().add_argument(*args, **kwargs)
        #   File ".../lib/python3.14/argparse.py", line 1562, in add_argument
        #     formatter = self._get_formatter()
        #   File ".../lib/python3.14/argparse.py", line 2729, in _get_formatter
        #     return self.formatter_class(
        #            ~~~~~~~~~~~~~~~~~~~~^
        #         prog=self.prog,
        #         ^^^^^^^^^^^^^^^
        #         prefix_chars=self.prefix_chars,
        #         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        #         color=self.color,
        #         ^^^^^^^^^^^^^^^^^
        #     )
        #     ^
        # TypeError: HelpFormatter.__init__() got an unexpected keyword argument 'prefix_chars'
        #
        # So we perform an alternated sanity check for 3.14.
        if sys.version_info[:2] < (3, 14):
            assert (
                "{version} from ".format(version=tox_version.raw)
                in subprocess.check_output(args=[tox_pex, "--version"]).decode("utf-8").strip()
            )
        else:
            assert ProjectName("tox") in {
                dist.metadata.project_name for dist in PEX(tox_pex).resolve()
            }

        cowsay_pex = tmpdir.join("cowsay.pex")
        run_pex_command(
            args=["--pylock", pdm_exported_pylock_toml, "-c", "cowsay", "-o", cowsay_pex]
        ).assert_success()

        assert ProjectName("tox") not in {
            dist.metadata.project_name for dist in PEX(cowsay_pex).resolve()
        }
        assert "| Moo! |" in subprocess.check_output(args=[cowsay_pex, "Moo!"]).decode("utf-8")
