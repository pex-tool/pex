# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import subprocess
import sys
import tempfile
from textwrap import dedent
from typing import Callable

import pytest

from pex.build_system import pep_517
from pex.cli.testing import run_pex3
from pex.common import safe_open
from pex.pip.version import PipVersion
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.result import try_
from pex.testing import IS_LINUX, PY39, PY310, ensure_python_interpreter, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Repo(object):
    find_links = attr.ib()  # type: str
    path_mapping = attr.ib()  # type: str


@pytest.fixture
def build_sdist(tmpdir):
    # type: (Any) -> Callable[[str], Repo]

    def func(project_directory):
        find_links = os.path.join(tmpdir, "find-links")
        path_mapping = "FL|{}".format(find_links)
        os.makedirs(find_links)
        try_(
            pep_517.build_sdist(
                project_directory=project_directory,
                dist_dir=find_links,
                pip_version=PipVersion.VENDORED,
                resolver=ConfiguredResolver.default(),
            )
        )
        return Repo(find_links=find_links, path_mapping=path_mapping)

    return func


def test_lock_uncompilable_sdist(
    tmpdir,  # type: Any
    build_sdist,  # type: Callable[[str], Repo]
):
    # type: (...) -> None

    project = os.path.join(str(tmpdir), "project")
    os.mkdir(project)
    with open(os.path.join(project, "bad.c"), "w") as fp:
        fp.write("This is not valid C code.")

    with open(os.path.join(project, "README"), "w") as fp:
        fp.write("This is a Python C-extension project that does not compile.")

    with open(os.path.join(project, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup, Extension


                setup(
                    name="bad",
                    version="0.1.0",
                    author="John Sirois",
                    author_email="js@example.com",
                    url="http://example.com/bad",
                    ext_modules=[Extension('bad',  sources=['bad.c'])],
                )
                """
            )
        )

    repo = build_sdist(project)

    lock = os.path.join(str(tmpdir), "lock.json")
    run_pex3(
        "lock",
        "create",
        "-f",
        repo.find_links,
        "bad",
        "--no-pypi",
        "--path-mapping",
        repo.path_mapping,
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()

    result = run_pex_command(args=["--lock", lock, "--path-mapping", repo.path_mapping])
    result.assert_failure()
    assert "bad-0.1.0.tar.gz" in result.error, result.error
    assert "ERROR: Failed to build one or more wheels" in result.error, result.error


@pytest.mark.skipif(not IS_LINUX, reason="The evdev project requires Linux.")
def test_pep_517_prepare_metadata_for_build_wheel_fallback(
    tmpdir,  # type: Any
    build_sdist,  # type: Callable[[str], Repo]
):
    # type: (...) -> None

    python = ensure_python_interpreter(PY310)

    evdev = os.path.join(str(tmpdir), "python-evdev")
    os.mkdir(evdev)
    subprocess.check_call(args=["git", "init"], cwd=evdev)
    evdev_1_6_1_sha = "2dd6ce6364bb67eedb209f6aa0bace0c18a3a40a"
    subprocess.check_call(
        args=[
            "git",
            "fetch",
            "--depth",
            "1",
            "https://github.com/gvalkov/python-evdev",
            evdev_1_6_1_sha,
        ],
        cwd=evdev,
    )
    subprocess.check_call(args=["git", "reset", "--hard", evdev_1_6_1_sha], cwd=evdev)
    with tempfile.NamedTemporaryFile() as fp:
        fp.write(
            dedent(
                """\
                diff --git a/builder/delegate_to_setuptools.py b/builder/delegate_to_setuptools.py
                new file mode 100644
                index 0000000..9a4d93d
                --- /dev/null
                +++ b/builder/delegate_to_setuptools.py
                @@ -0,0 +1,6 @@
                +from setuptools import build_meta
                +
                +
                +build_sdist = build_meta.build_sdist
                +build_wheel = build_meta.build_wheel
                +
                diff --git a/pyproject.toml b/pyproject.toml
                new file mode 100644
                index 0000000..7c52595
                --- /dev/null
                +++ b/pyproject.toml
                @@ -0,0 +1,5 @@
                +[build-system]
                +requires = ["setuptools==67.2.0", "wheel==0.38.4"]
                +backend-path = ["builder"]
                +build-backend = "delegate_to_setuptools"
                +
                diff --git a/setup.py b/setup.py
                index 73ba1f5..c19fa76 100755
                --- a/setup.py
                +++ b/setup.py
                @@ -41,7 +41,7 @@ ecodes_c = Extension('evdev._ecodes', sources=['evdev/ecodes.c'], extra_compile_
                 #-----------------------------------------------------------------------------
                 kw = {
                     'name':                 'evdev',
                -    'version':              '1.6.1',
                +    'version':              '1.6.1+test',

                     'description':          'Bindings to the Linux input handling subsystem',
                     'long_description':     (curdir / 'README.rst').read_text(),
                @@ -53,7 +53,7 @@ kw = {
                     'url':                  'https://github.com/gvalkov/python-evdev',
                     'classifiers':          classifiers,

                -    'packages':             ['evdev'],
                +    'packages':             ['evdev', 'builder'],
                     'ext_modules':          [input_c, uinput_c, ecodes_c],
                     'include_package_data': False,
                     'zip_safe':             True,
                """
            ).encode("utf-8")
        )
        fp.flush()
        subprocess.check_call(args=["git", "apply", fp.name], cwd=evdev)

    repo = build_sdist(evdev)

    lock = os.path.join(str(tmpdir), "lock.json")
    result = run_pex3(
        "lock",
        "create",
        "-vvv",
        "--python",
        python,
        "-f",
        repo.find_links,
        "evdev==1.6.1+test",
        "--path-mapping",
        repo.path_mapping,
        "--indent",
        "2",
        "-o",
        lock,
    )
    result.assert_success()

    assert re.search(
        r"Failed to prepare metadata for .+{}, trying to build a wheel instead: ".format(
            re.escape("evdev-1.6.1+test.tar.gz")
        ),
        result.error,
    ), result.error
