# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import filecmp
import os
import sys
from textwrap import dedent
from zipfile import ZipFile

import pytest

from pex.common import safe_open, temporary_dir
from pex.compatibility import PY2
from pex.interpreter import PythonInterpreter
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve.lockfile import json_codec
from pex.targets import LocalInterpreter
from pex.typing import TYPE_CHECKING
from testing import (
    IS_LINUX_ARM64,
    IS_MAC_ARM64,
    IS_PYPY,
    PY27,
    PY38,
    PY39,
    PY310,
    PY_VER,
    create_pex_command,
    ensure_python_interpreter,
    run_command_with_jitter,
    run_commands_with_jitter,
)
from testing.cli import run_pex3
from testing.pytest.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Iterable, List, Optional, Tuple


def compatible_pip_version(pythons):
    # type: (Iterable[str]) -> PipVersionValue
    for pip_version in sorted(PipVersion.values(), key=lambda v: v.version, reverse=True):
        if all(
            pip_version.requires_python_applies(
                LocalInterpreter.create(PythonInterpreter.from_binary(python))
            )
            for python in pythons
        ):
            return pip_version
    raise AssertionError(
        "Expected there to be a --pip-version compatible with all pythons: {pythons}".format(
            pythons=", ".join(pythons)
        )
    )


def assert_reproducible_build(
    args,  # type: List[str]
    pythons=None,  # type: Optional[Iterable[str]]
):
    # type: (...) -> None
    with temporary_dir() as td:

        def explode_pex(path):
            with ZipFile(path) as zf:
                pex_name, _ = os.path.splitext(path)
                destination_dir = os.path.join(td, "pex{}".format(pex_name))
                zf.extractall(path=destination_dir)
                return [os.path.join(destination_dir, member) for member in sorted(zf.namelist())]

        if pythons:
            pexes = run_commands_with_jitter(
                path_argument="--output-file",
                commands=[
                    create_pex_command(
                        args=args + ["--python-shebang", "/usr/bin/env python"],
                        python=python,
                        quiet=True,
                    )
                    for python in pythons
                ],
            )
        else:
            pexes = run_command_with_jitter(
                create_pex_command(args=args, quiet=True), path_argument="--output-file", count=3
            )

        pex_members = {pex: explode_pex(path=pex) for pex in pexes}
        pex1 = pexes.pop()
        for pex2 in pexes:
            # First compare file-by-file for easier debugging.
            for member1, member2 in zip(pex_members[pex1], pex_members[pex2]):
                assert not os.path.isdir(member1) ^ os.path.isdir(member2)
                if os.path.isdir(member1):
                    continue
                # Check that each file has the same content.
                with open(member1, "rb") as f1, open(member2, "rb") as f2:
                    assert list(f1.readlines()) == list(
                        f2.readlines()
                    ), "{} and {} have different content.".format(member1, member2)
                # Check that the entire file is equal, including metadata.
                assert filecmp.cmp(member1, member2, shallow=False)
            # Finally, check that the .pex files are byte-for-byte identical.
            assert filecmp.cmp(pex1, pex2, shallow=False)


@pytest.fixture(scope="module")
def major_compatible_pythons():
    # type: () -> Tuple[str, ...]
    return (
        (sys.executable, ensure_python_interpreter(PY27))
        if PY2
        else (sys.executable, ensure_python_interpreter(PY39), ensure_python_interpreter(PY310))
    )


@pytest.fixture(scope="module")
def mixed_major_pythons():
    # type: () -> Tuple[str, ...]
    return (
        sys.executable,
        ensure_python_interpreter(PY27),
        ensure_python_interpreter(PY38),
        ensure_python_interpreter(PY310),
    )


def test_reproducible_build_no_args(mixed_major_pythons):
    # type: (Tuple[str, ...]) -> None
    assert_reproducible_build([], pythons=mixed_major_pythons)


@pytest.mark.skipif(
    ((IS_MAC_ARM64 or IS_LINUX_ARM64) and PY_VER != (3, 6))
    or PY_VER > (3, 10)
    or (IS_PYPY and PY_VER > (3, 7)),
    reason=(
        "There are no pre-built binaries for the cryptography distribution for PyPy 3.8+, or "
        "for CPython 2.7 on macOS/Linux ARM64. There are also no pre-built binaries for its "
        "transitive dependency on cffi for CPython 3.11+; so this test fails for those "
        "interpreters since it requires building an sdist and that leads to an underlying C `.so`"
        "build that we have insufficient control over to make reproducible."
    ),
)
def test_reproducible_build_bdist_requirements():
    # type: () -> None
    # We test both a pure Python wheel (six) and a platform-specific wheel (cryptography).
    assert_reproducible_build(
        [
            "six==1.12.0",
            "cryptography=={version}".format(version="2.6.1" if PY2 else "3.4.8"),
        ]
    )


def test_reproducible_build_sdist_requirements(major_compatible_pythons):
    # type: (Tuple[str, ...]) -> None
    # The python-crontab sdist will be built as py2-none-any or py3-none-any depending on the
    # Python major version since it is not marked as universal in the sdist.
    assert_reproducible_build(
        [
            "python-crontab==2.3.6",
            "--pip-version",
            str(compatible_pip_version(major_compatible_pythons)),
        ],
        pythons=major_compatible_pythons,
    )


def test_reproducible_build_m_flag(mixed_major_pythons):
    # type: (Tuple[str, ...]) -> None
    assert_reproducible_build(["-m", "pydoc"], pythons=mixed_major_pythons)


def find_compatible_setuptools(pythons):
    # type: (Iterable[str]) -> Version
    py_versions = sorted(PythonInterpreter.from_binary(py).version for py in pythons)
    assert len(py_versions) > 0
    min_py_version = py_versions[0]
    max_py_version = py_versions[-1]
    interpreter_constraint = ">={min},<={max}".format(
        min=".".join(map(str, min_py_version)), max=".".join(map(str, max_py_version))
    )
    result = run_pex3(
        "lock",
        "create",
        "--interpreter-constraint",
        interpreter_constraint,
        "--style",
        "universal",
        "setuptools",
    )
    result.assert_success()
    lockfile = json_codec.loads(result.output)
    assert len(lockfile.locked_resolves) == 1
    locked_requirements = {
        locked_req.pin.project_name: locked_req.pin.version
        for locked_req in lockfile.locked_resolves[0].locked_requirements
    }
    return locked_requirements.pop(ProjectName("setuptools"))


def test_reproducible_build_c_flag_from_source(
    tmpdir,  # type: Tempdir
    major_compatible_pythons,  # type: Tuple[str, ...]
):
    # type: (...) -> None

    # We go through some hoops here to find a setuptools version that works for all
    # major_compatible_pythons to ensure we don't introduce variability though a changing setuptools
    # version.
    setuptools_version = find_compatible_setuptools(major_compatible_pythons)

    project_dir = tmpdir.join("project")
    with safe_open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools=={version}"]
                build-backend =  "setuptools.build_meta"
                """.format(
                    version=setuptools_version
                )
            )
        )
    with safe_open(os.path.join(project_dir, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [bdist_wheel]
                python_tag=py2.py3
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup

                setup(
                    name="my_app",
                    entry_points={"console_scripts": ["my_app_function = my_app:do_something"]},
                )
                """
            )
        )
    with safe_open(os.path.join(project_dir, "my_app.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                def do_something():
                    return "reproducible"
                """
            )
        )

    assert_reproducible_build(
        [
            project_dir,
            "-c",
            "my_app_function",
            "--pip-version",
            str(compatible_pip_version(major_compatible_pythons)),
        ],
        # Modern Pip / Setuptools produce different metadata for sdists than legacy Pip /
        # Setuptools; so we don't mix them.
        pythons=major_compatible_pythons,
    )


def test_reproducible_build_c_flag_from_dependency(major_compatible_pythons):
    # type: (Tuple[str, ...]) -> None
    # The futurize script installed depends on the version of python being used; so we don't try
    # to mix Python 2 with Python 3 as in many other reproducibility tests.
    assert_reproducible_build(
        [
            "future==0.17.1",
            "-c",
            "futurize",
            "--pip-version",
            str(compatible_pip_version(major_compatible_pythons)),
        ],
        pythons=major_compatible_pythons,
    )


def test_reproducible_build_python_flag(mixed_major_pythons):
    # type: (Tuple[str, ...]) -> None
    assert_reproducible_build(
        ["--python", "python2.7", "--python-path", os.pathsep.join(mixed_major_pythons)],
        pythons=mixed_major_pythons,
    )


def test_reproducible_build_python_shebang_flag():
    # type: () -> None
    # Passing `python_versions` override `--python-shebang`; so we don't do that here.
    assert_reproducible_build(["--python-shebang=/usr/bin/python"])
