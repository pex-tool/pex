# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

import pytest

from pex.interpreter import PythonInterpreter
from pex.resolve import lockfile
from pex.resolve.locked_resolve import LockedResolve
from pex.targets import LocalInterpreter, Target
from pex.testing import (
    IS_MAC,
    PY27,
    PY37,
    PY310,
    IntegResults,
    ensure_python_interpreter,
    run_pex_command,
)
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Mapping


SINGLE_PLATFORM_UNIVERSAL_WHEEL = lockfile.loads(
    dedent(
        """\
        {
          "allow_builds": true,
          "allow_prereleases": false,
          "allow_wheels": true,
          "build_isolation": true,
          "constraints": [],
          "locked_resolves": [
            {
              "locked_requirements": [
                {
                  "artifacts": [
                    {
                      "algorithm": "sha256",
                      "hash": "00d2dde5a675579325902536738dd27e4fac1fd68f773fe36c21044eb559e187",
                      "url": "http://localhost:9999/ansicolors-1.1.8-py2.py3-none-any.whl"
                    }
                  ],
                  "project_name": "ansicolors",
                  "requires_dists": [],
                  "requires_python": null,
                  "version": "1.1.8"
                }
              ],
              "platform_tag": [
                "cp27",
                "cp27mu",
                "manylinux_2_33_x86_64"
              ]
            }
          ],
          "pex_version": "2.1.50",
          "prefer_older_binary": false,
          "requirements": [
            "ansicolors"
          ],
          "requires_python": [],
          "resolver_version": "pip-legacy-resolver",
          "style": "strict",
          "transitive": true,
          "use_pep517": null
        }
        """
    )
)


def test_select_no_targets():
    # type: () -> None
    assert [] == list(SINGLE_PLATFORM_UNIVERSAL_WHEEL.select([]))


def create_target(python_version):
    # type: (str) -> Target
    return LocalInterpreter.create(
        PythonInterpreter.from_binary(ensure_python_interpreter(python_version))
    )


@pytest.fixture
def py27():
    return create_target(PY27)


@pytest.fixture
def py37():
    return create_target(PY37)


@pytest.fixture
def py310():
    return create_target(PY310)


def test_select_same_target(py27):
    # type: (Target) -> None
    assert [(py27, SINGLE_PLATFORM_UNIVERSAL_WHEEL.locked_resolves[0])] == list(
        SINGLE_PLATFORM_UNIVERSAL_WHEEL.select([py27])
    )


def test_select_universal_compatible_targets(
    py37,  # type: Target
    py310,  # type: Target
):
    # type: (...) -> None
    assert [
        (py37, SINGLE_PLATFORM_UNIVERSAL_WHEEL.locked_resolves[0]),
        (py310, SINGLE_PLATFORM_UNIVERSAL_WHEEL.locked_resolves[0]),
    ] == list(SINGLE_PLATFORM_UNIVERSAL_WHEEL.select([py37, py310]))


DUAL_PLATFORM_NATIVE_WHEEL = lockfile.loads(
    dedent(
        """\
        {
          "allow_builds": true,
          "allow_prereleases": false,
          "allow_wheels": true,
          "build_isolation": true,
          "constraints": [],
          "locked_resolves": [
            {
              "locked_requirements": [
                {
                  "artifacts": [
                    {
                      "algorithm": "sha256",
                      "hash": "5f08ba37b662b9a1d9bcabb457d77eaac4b3c755e623ed77dfe2cd2eba60f6af",
                      "url": "file:///find_links/p537-1.0.4-cp37-cp37m-macosx_10_13_x86_64.whl"
                    }
                  ],
                  "project_name": "p537",
                  "requires_dists": [],
                  "requires_python": null,
                  "version": "1.0.4"
                }
              ],
              "platform_tag": [
                "cp37",
                "cp37m",
                "macosx_10_13_x86_64"
              ]
            },
            {
              "locked_requirements": [
                {
                  "artifacts": [
                    {
                      "algorithm": "sha256",
                      "hash": "20129f25683fab2099d954379fecd36c13ccc0cc0159eaf59afee53a23d749f1",
                      "url": "http://localhost:9999/p537-1.0.4-cp37-cp37m-manylinux1_x86_64.whl"
                    }
                  ],
                  "project_name": "p537",
                  "requires_dists": [],
                  "requires_python": null,
                  "version": "1.0.4"
                }
              ],
              "platform_tag": [
                "cp37",
                "cp37m",
                "manylinux2014_x86_64"
              ]
            }
          ],
          "pex_version": "2.1.50",
          "prefer_older_binary": false,
          "requirements": [
            "p537"
          ],
          "requires_python": [],
          "resolver_version": "pip-legacy-resolver",
          "style": "strict",
          "transitive": true,
          "use_pep517": null
        }
        """
    )
)


def test_select_incompatible_target(py27):
    # type: (Target) -> None
    assert [] == list(DUAL_PLATFORM_NATIVE_WHEEL.select([py27]))


def test_select_compatible_targets(
    py37,  # type: Target
    py310,  # type: Target
):
    # type: (...) -> None
    expected_index = 0 if IS_MAC else 1
    assert [(py37, DUAL_PLATFORM_NATIVE_WHEEL.locked_resolves[expected_index])] == list(
        DUAL_PLATFORM_NATIVE_WHEEL.select([py37, py310])
    )


LOCK_STYLE_SOURCES = lockfile.loads(
    dedent(
        """\
        {
          "allow_builds": true,
          "allow_prereleases": false,
          "allow_wheels": true,
          "build_isolation": true,
          "constraints": [],
          "locked_resolves": [
            {
              "locked_requirements": [
                {
                  "artifacts": [
                    {
                      "algorithm": "sha256",
                      "hash": "20129f25683fab2099d954379fecd36c13ccc0cc0159eaf59afee53a23d749f1",
                      "url": "https://files.pythonhosted.org/packages/7c/39/fcd0a978eb327ce8d170ee763264cee1a3a43b0e5f962312d4a37567523d/p537-1.0.4-cp37-cp37m-manylinux1_x86_64.whl"
                    },
                    {
                      "algorithm": "sha256",
                      "hash": "b1818f434c559706039fa6ca9812f120fc6421b977d5862fb7b411ebaffc074f",
                      "url": "https://files.pythonhosted.org/packages/56/05/6f01bef57523f6ab7ba5b8fa9831a2204c7ef49dfc194c0d689863f3ae1c/p537-1.0.4.tar.gz"
                    }
                  ],
                  "project_name": "p537",
                  "requires_dists": [],
                  "requires_python": null,
                  "version": "1.0.4"
                }
              ],
              "platform_tag": [
                "cp37",
                "cp37m",
                "manylinux_2_33_x86_64"
              ]
            }
          ],
          "pex_version": "2.1.50",
          "prefer_older_binary": false,
          "requirements": [
            "p537==1.0.4"
          ],
          "requires_python": [],
          "resolver_version": "pip-legacy-resolver",
          "style": "sources",
          "transitive": true,
          "use_pep517": null
        }
        """
    )
)


def test_lockfile_style_sources(
    py27,  # type: Target
    py37,  # type: Target
    tmpdir,  # type: Any
):
    # type: (...) -> None

    selected = {
        target: locked_resolve for target, locked_resolve in LOCK_STYLE_SOURCES.select([py27, py37])
    }  # type: Mapping[Target, LockedResolve]
    assert {
        py27: LOCK_STYLE_SOURCES.locked_resolves[0],
        py37: LOCK_STYLE_SOURCES.locked_resolves[0],
    } == selected

    def use_lock(target):
        # type: (Target) -> IntegResults
        locked_requirements_file = os.path.join(
            str(tmpdir), "requirements.{}.lock".format(target.id)
        )
        with open(locked_requirements_file, "w") as fp:
            selected[target].emit_requirements(fp)
        return run_pex_command(
            args=["-r", locked_requirements_file, "--", "-c", "import p537"],
            python=target.get_interpreter().binary,
        )

    use_lock(py37).assert_success()

    # N.B.: We created a lock above that falsely advertises there is a solution for Python 2.7.
    # This is the devil's bargain with non-strict lock styles and the lock will fail only some time
    # later when it is exercised using the wrong interpreter.
    result = use_lock(py27)
    result.assert_failure()
    assert "Building wheel for p537 (setup.py): started" in result.error
    assert "Building wheel for p537 (setup.py): finished with status 'error'" in result.error
