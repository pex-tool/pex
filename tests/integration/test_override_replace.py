# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import shutil
import subprocess
from textwrap import dedent
from typing import List

import pytest

from pex.common import safe_mkdir, safe_open
from pex.interpreter import PythonInterpreter
from pex.pep_503 import ProjectName
from pex.resolve.lockfile import json_codec
from pex.typing import TYPE_CHECKING
from testing import PY39, PY310, PY311, WheelBuilder, ensure_python_interpreter, run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    import colors  # vendor:skip
else:
    from pex.third_party import colors


def add_build_system_boilerplate(project_dir):
    # type: (str) -> None

    with safe_open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools"]
                build-backend = "setuptools.build_meta"
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup


                setup()
                """
            )
        )


@pytest.fixture
def project_with_ansicolors_dep(tmpdir):
    # type: (Tempdir) -> str

    project_dir = tmpdir.join("project")
    add_build_system_boilerplate(project_dir)
    with safe_open(os.path.join(project_dir, "module.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import sys

                import colors


                def print_green():
                    print(colors.green("Green?"))


                if __name__ == "__main__":
                    print_green()
                    sys.exit(0)
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = module
                version = 0.1.0

                [options]
                py_modules = module
                install_requires =
                    ansicolors==1.1.8

                [options.entry_points]
                console_scripts =
                    script = module:print_green

                [bdist_wheel]
                python_tag=py2.py3
                """
            )
        )
    return WheelBuilder(project_dir).bdist()


def create_custom_ansicolors(
    tmpdir,  # type: Tempdir
    project_name,  # type: str
    green_code,  # type: str
):
    # type: (...) -> str

    project_dir = tmpdir.join(project_name)
    add_build_system_boilerplate(project_dir)
    with safe_open(os.path.join(project_dir, "colors.py"), "w") as fp:
        fp.write(green_code)
    with safe_open(os.path.join(project_dir, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = {project_name}
                version = 0.1.0

                [options]
                py_modules = colors

                [bdist_wheel]
                python_tag=py2.py3
                """
            ).format(project_name=project_name)
        )
    return project_dir


@pytest.fixture
def my_ansicolors_asterisks(tmpdir):
    # type: (Tempdir) -> str

    return create_custom_ansicolors(
        tmpdir=tmpdir,
        project_name="my_ansicolors_asterisks",
        green_code=dedent(
            """\
            def green(text):
                return "*** {text} ***".format(text=text)
            """
        ),
    )


@pytest.fixture
def my_ansicolors_dashes(tmpdir):
    # type: (Tempdir) -> str

    return create_custom_ansicolors(
        tmpdir=tmpdir,
        project_name="my_ansicolors_dashes",
        green_code=dedent(
            """\
            def green(text):
                return "--- {text} ---".format(text=text)
            """
        ),
    )


@pytest.fixture
def find_links_repo(
    tmpdir,  # type: Tempdir
    my_ansicolors_asterisks,  # type: str
    my_ansicolors_dashes,  # type: str
):
    # type: (...) -> str

    my_ansicolors_asterisks_wheel = WheelBuilder(my_ansicolors_asterisks).bdist()
    my_ansicolors_dashes_wheel = WheelBuilder(my_ansicolors_dashes).bdist()

    find_links_repo = safe_mkdir(tmpdir.join("find-links"))
    shutil.copy(
        my_ansicolors_asterisks_wheel,
        os.path.join(find_links_repo, os.path.basename(my_ansicolors_asterisks_wheel)),
    )
    shutil.copy(
        my_ansicolors_dashes_wheel,
        os.path.join(find_links_repo, os.path.basename(my_ansicolors_dashes_wheel)),
    )
    return find_links_repo


def version(interpreter):
    # type: (PythonInterpreter) -> str
    return "{major}.{minor}".format(major=interpreter.version[0], minor=interpreter.version[1])


ANSICOLORS_PYTHON = PythonInterpreter.get()
ASTERISKS_PYTHON = PythonInterpreter.from_binary(
    ensure_python_interpreter(PY310 if version(ANSICOLORS_PYTHON) == "3.11" else PY311)
)
DASHES_PYTHON = PythonInterpreter.from_binary(ensure_python_interpreter(PY39))


def assert_multi_override_pex(
    tmpdir,  # type: Tempdir
    extra_pex_args,  # type: List[str]
    is_exhaustive_override,  # type: bool
):
    # type: (...) -> None

    pex = tmpdir.join("pex")
    pex_root = tmpdir.join("pex-root")
    args = [
        "--pex-root",
        pex_root,
        "--runtime-pex-root",
        pex_root,
        "--python",
        ASTERISKS_PYTHON.binary,
        "--python",
        DASHES_PYTHON.binary,
        "-c",
        "script",
        "-o",
        pex,
    ]
    if not is_exhaustive_override:
        args.append("--python")
        args.append(ANSICOLORS_PYTHON.binary)
    args.extend(extra_pex_args)

    run_pex_command(args=args).assert_success()
    if not is_exhaustive_override:
        assert (
            colors.green("Green?")
            == subprocess.check_output(args=[ANSICOLORS_PYTHON.binary, pex]).decode("utf-8").strip()
        )
    assert (
        "*** Green? ***"
        == subprocess.check_output(args=[ASTERISKS_PYTHON.binary, pex]).decode("utf-8").strip()
    )
    assert (
        "--- Green? ---"
        == subprocess.check_output(args=[DASHES_PYTHON.binary, pex]).decode("utf-8").strip()
    )


@pytest.fixture
def multi_override_args(
    find_links_repo,  # type: str
    project_with_ansicolors_dep,  # type: str
):
    # type: (...) -> List[str]

    return [
        "--find-links",
        find_links_repo,
        "--override",
        "ansicolors=my-ansicolors-asterisks; python_version == '{version}'".format(
            version=version(ASTERISKS_PYTHON)
        ),
        "--override",
        "ansicolors=my-ansicolors-dashes; python_version == '{version}'".format(
            version=version(DASHES_PYTHON)
        ),
        project_with_ansicolors_dep,
    ]


def test_replace_pex(
    tmpdir,  # type: Tempdir
    project_with_ansicolors_dep,  # type: str
    find_links_repo,  # type: str
    multi_override_args,  # type: List[str]
):
    # type: (...) -> None

    pex = tmpdir.join("pex")
    run_pex_command(args=[project_with_ansicolors_dep, "-c", "script", "-o", pex]).assert_success()
    assert colors.green("Green?") == subprocess.check_output(args=[pex]).decode("utf-8").strip()

    run_pex_command(
        args=[
            "--find-links",
            find_links_repo,
            project_with_ansicolors_dep,
            "-c",
            "script",
            "-o",
            pex,
        ]
    ).assert_success()
    assert colors.green("Green?") == subprocess.check_output(args=[pex]).decode("utf-8").strip()

    run_pex_command(
        args=[
            "--find-links",
            find_links_repo,
            "--override",
            "ansicolors=my-ansicolors-asterisks",
            project_with_ansicolors_dep,
            "-c",
            "script",
            "-o",
            pex,
        ]
    ).assert_success()
    assert "*** Green? ***" == subprocess.check_output(args=[pex]).decode("utf-8").strip()

    assert_multi_override_pex(tmpdir, multi_override_args, is_exhaustive_override=False)


def test_replace_lock_partial(
    tmpdir,  # type: Tempdir
    project_with_ansicolors_dep,  # type: str
    find_links_repo,  # type: str
    multi_override_args,  # type: List[str]
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    lock = tmpdir.join("lock.json")
    lock_args = [
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--style",
        "universal",
        "--interpreter-constraint",
        ">=3.9,<3.12",
        "--indent",
        "2",
        "-o",
        lock,
    ] + multi_override_args

    run_pex3(*lock_args).assert_success()
    assert_multi_override_pex(tmpdir, ["--lock", lock], is_exhaustive_override=False)
    assert_multi_override_pex(
        tmpdir, ["--lock", lock, project_with_ansicolors_dep], is_exhaustive_override=False
    )

    run_pex3(*(lock_args + ["--elide-unused-requires-dist", "-v"])).assert_success()
    assert_multi_override_pex(tmpdir, ["--lock", lock], is_exhaustive_override=False)
    assert_multi_override_pex(
        tmpdir, ["--lock", lock, project_with_ansicolors_dep], is_exhaustive_override=False
    )


def assert_no_ansicolors(lock):
    # type: (str) -> None

    lockfile = json_codec.load(lock)
    locked_projects = {
        locked_requirement.pin.project_name
        for locked_resolve in lockfile.locked_resolves
        for locked_requirement in locked_resolve.locked_requirements
    }
    assert ProjectName("ansicolors") not in locked_projects


def test_replace_lock_full(
    tmpdir,  # type: Tempdir
    project_with_ansicolors_dep,  # type: str
    find_links_repo,  # type: str
    multi_override_args,  # type: List[str]
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    lock = tmpdir.join("lock.json")
    lock_args = [
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--style",
        "universal",
        "--indent",
        "2",
        "-o",
        lock,
    ] + multi_override_args
    for interpreter in ASTERISKS_PYTHON, DASHES_PYTHON:
        lock_args.append("--interpreter-constraint")
        lock_args.append("=={version}.*".format(version=interpreter.python))

    run_pex3(*lock_args).assert_success()
    assert_no_ansicolors(lock)
    assert_multi_override_pex(tmpdir, ["--lock", lock], is_exhaustive_override=True)

    run_pex3(*(lock_args + ["--elide-unused-requires-dist", "-v"])).assert_success()
    assert_no_ansicolors(lock)
    assert_multi_override_pex(tmpdir, ["--lock", lock], is_exhaustive_override=True)
