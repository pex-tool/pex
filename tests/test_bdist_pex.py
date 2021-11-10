# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from contextlib import contextmanager
from textwrap import dedent

from pex import resolver
from pex.common import open_zip, temporary_dir
from pex.interpreter import spawn_python_job
from pex.testing import WheelBuilder, make_project, pex_project_dir, temporary_content
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, List, Iterator, Iterable, Optional, Text, Union


BDIST_PEX_PYTHONPATH = None


def bdist_pex_pythonpath():
    # type: () -> List[str]
    # In order to run the bdist_pex distutils command we need:
    # 1. setuptools on the PYTHONPATH since the test projects use and test setuptools.setup and its
    #    additional features above and beyond distutils.core.setup like entry points declaration.
    # 2. Pex on the PYTHONPATH so its distutils command module(s) can be found.
    # 3. An indication to distutils of where to look for Pex distutils commands.
    #
    # We take care of 1 and 2 here and 3 is taken care of by passing --command-packages to distutils.

    global BDIST_PEX_PYTHONPATH
    if BDIST_PEX_PYTHONPATH is None:
        BDIST_PEX_PYTHONPATH = [pex_project_dir()]

        # Although the setuptools version is not important, we pick one so the test can leverage the
        # pex cache for speed run over run.
        BDIST_PEX_PYTHONPATH.extend(
            installed_distribution.distribution.location
            for installed_distribution in resolver.resolve(
                ["setuptools==43.0.0"]
            ).installed_distributions
        )
    return BDIST_PEX_PYTHONPATH


@contextmanager
def bdist_pex(project_dir, bdist_args=None):
    # type: (str, Optional[Iterable[str]]) -> Iterator[List[str]]
    with temporary_dir() as dist_dir:
        cmd = [
            "setup.py",
            "--command-packages",
            "pex.commands",
            "bdist_pex",
            "--bdist-dir={}".format(dist_dir),
        ]
        if bdist_args:
            cmd.extend(bdist_args)

        spawn_python_job(args=cmd, cwd=project_dir, pythonpath=bdist_pex_pythonpath()).wait()
        yield [os.path.join(dist_dir, dir_entry) for dir_entry in os.listdir(dist_dir)]


def assert_entry_points(entry_points, bdist_args=None):
    # type: (Union[str, Dict[str, List[str]]], Optional[Iterable[str]]) -> Iterator[str]
    with make_project(name="my_app", entry_points=entry_points) as project_dir:
        with bdist_pex(project_dir, bdist_args) as apps_pex:
            for app_pex in apps_pex:
                process = subprocess.Popen([app_pex], stdout=subprocess.PIPE)
                stdout, _ = process.communicate()
                assert "{pex_root}" not in os.listdir(project_dir)
                assert 0 == process.returncode
                assert stdout == b"hello world!\n"
                yield os.path.basename(app_pex)


def assert_pex_args_shebang(shebang):
    # type: (str) -> None
    with make_project() as project_dir:
        pex_args = '--pex-args=--python-shebang="{}"'.format(shebang)
        with bdist_pex(project_dir, bdist_args=[pex_args]) as (my_app_pex,):
            with open(my_app_pex, "rb") as fp:
                assert fp.readline().decode().rstrip() == shebang


def test_entry_points_dict():
    # type: () -> None
    (_,) = assert_entry_points({"console_scripts": ["my_app = my_app.my_module:do_something"]})


def test_entry_points_ini_string():
    # type: () -> None
    (_,) = assert_entry_points(
        dedent(
            """
            [console_scripts]
            my_app=my_app.my_module:do_something
            """
        )
    )


def test_bdist_all_single_entry_point_dict():
    # type: () -> None
    assert {"first_app"} == set(
        assert_entry_points(
            {"console_scripts": ["first_app = my_app.my_module:do_something"]}, ["--bdist-all"]
        )
    )


def test_bdist_all_two_entry_points_dict():
    # type: () -> None
    assert {"first_app", "second_app"} == set(
        assert_entry_points(
            {
                "console_scripts": [
                    "first_app = my_app.my_module:do_something",
                    "second_app = my_app.my_module:do_something",
                ]
            },
            ["--bdist-all"],
        )
    )


def test_bdist_all_single_entry_point_ini_string():
    # type: () -> None
    (my_app,) = assert_entry_points(
        dedent(
            """
            [console_scripts]
            my_app=my_app.my_module:do_something
            """
        ),
        ["--bdist-all"],
    )
    assert "my_app" == my_app


def test_bdist_all_two_entry_points_ini_string():
    # type: () -> None
    assert {"first_app", "second_app"} == set(
        assert_entry_points(
            dedent(
                """
            [console_scripts]
            first_app=my_app.my_module:do_something
            second_app=my_app.my_module:do_something
            """
            ),
            ["--bdist-all"],
        )
    )


def test_pex_args_shebang_with_spaces():
    # type: () -> None
    assert_pex_args_shebang("#!/usr/bin/env python")


def test_pex_args_shebang_without_spaces():
    # type: () -> None
    assert_pex_args_shebang("#!/usr/bin/python")


def test_unwriteable_contents():
    # type: () -> None
    my_app_setup_py = dedent(
        """
        from setuptools import setup
        
        setup(
            name='my_app',
            version='0.0.0',
            zip_safe=True,
            packages=['my_app'],
            include_package_data=True,
            package_data={'my_app': ['unwriteable.so']},
        )
        """
    )

    UNWRITEABLE_PERMS = 0o400
    with temporary_content(
        {
            "setup.py": my_app_setup_py,
            "my_app/__init__.py": "",
            "my_app/unwriteable.so": "so contents",
        },
        perms=UNWRITEABLE_PERMS,
    ) as my_app_project_dir:
        my_app_whl = WheelBuilder(my_app_project_dir).bdist()

        with make_project(name="uses_my_app", install_reqs=["my_app"]) as uses_my_app_project_dir:
            pex_args = "--pex-args=--disable-cache --no-pypi -f {}".format(
                os.path.dirname(my_app_whl)
            )
            with bdist_pex(uses_my_app_project_dir, bdist_args=[pex_args]) as (uses_my_app_pex,):
                with open_zip(uses_my_app_pex) as zf:
                    unwriteable_sos = [
                        path for path in zf.namelist() if path.endswith("my_app/unwriteable.so")
                    ]
                    assert 1 == len(unwriteable_sos)
                    unwriteable_so = unwriteable_sos.pop()
                    zf.extract(unwriteable_so, path=uses_my_app_project_dir)
                    extract_dest = os.path.join(uses_my_app_project_dir, unwriteable_so)
                    with open(extract_dest) as fp:
                        assert "so contents" == fp.read()
