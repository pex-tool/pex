# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest

from pex import sh_boot
from pex.compatibility import ConfigParser
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import InterpreterConstraints, iter_compatible_versions
from pex.orderedset import OrderedSet
from pex.pep_425 import CompatibilityTags
from pex.pep_508 import MarkerEnvironment
from pex.resolve import abbreviated_platforms
from pex.sh_boot import PythonBinaryName
from pex.targets import CompletePlatform, Targets
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Iterable, List


def calculate_binary_names(
    targets=Targets(),  # type: Targets
    interpreter_constraints=(),  # type: Iterable[str]
):
    return list(
        sh_boot._calculate_applicable_binary_names(
            targets=targets,
            interpreter_constraints=InterpreterConstraints.parse(*interpreter_constraints),
        )
    )


@pytest.fixture
def requires_python(pex_project_dir):
    # type: (str) -> str
    requires_python = os.environ.get("_PEX_REQUIRES_PYTHON")
    if requires_python:
        return requires_python

    config_parser = ConfigParser()
    config_parser.read(os.path.join(pex_project_dir, "setup.cfg"))
    return cast(str, config_parser.get("options", "python_requires"))


def expected(
    requires_python,  # type: str
    *names  # type: PythonBinaryName
):
    # type: (...) -> List[str]

    current_interpreter_identity = PythonInterpreter.get().identity

    # The default expected set of interpreters should always include:
    # 1. The targeted interpreters or the current interpreter if none were explicitly targeted.
    # 2. The interpreters Pex supports, CPython 1st since its faster to boot and re-exec with even
    #    if PyPy is what will be re-exec'd to. Also, newest version 1st since these are more likely
    #    to match the final interpreter than the reverse.
    # 3. Partially abbreviated names for the above in corresponding order.
    # 4. Fully abbreviated names for the above in corresponding order.
    all_names = OrderedSet(name.render(version_components=2) for name in names)
    if not names:
        all_names.add(current_interpreter_identity.binary_name(version_components=2))

    supported_versions = sorted(
        (version[:2] for version in set(iter_compatible_versions([requires_python]))),
        reverse=True,  # Newest (highest) version 1st.
    )
    for exe_name in "python", "pypy":
        all_names.update(
            "{exe_name}{major}.{minor}".format(exe_name=exe_name, major=major, minor=minor)
            for major, minor in supported_versions
        )

    if names:
        all_names.update(name.render(version_components=1) for name in names)
    else:
        all_names.add(current_interpreter_identity.binary_name(version_components=1))
    all_names.update(
        [
            "python3",
            "python2",
            "pypy3",
            "pypy2",
        ]
    )

    if names:
        all_names.update(name.render(version_components=0) for name in names)
    else:
        all_names.add(current_interpreter_identity.binary_name(version_components=0))
    all_names.update(
        [
            "python",
            "pypy",
        ]
    )

    return list(all_names)


def test_calculate_no_targets_no_ics(requires_python):
    # type: (str) -> None

    assert expected(requires_python) == calculate_binary_names()


def test_calculate_platforms_no_ics(requires_python):
    # type: (str) -> None

    assert expected(
        requires_python,
        PythonBinaryName(name="python", version=(3, 6)),
        PythonBinaryName(name="pypy", version=(2, 7)),
    ) == calculate_binary_names(
        Targets(
            platforms=(
                abbreviated_platforms.create("macosx-10.13-x86_64-cp-36-cp36m"),
                abbreviated_platforms.create("linux-x86_64-pp-27-pypy_73"),
            )
        )
    )


def test_calculate_interpreters_no_ics(
    requires_python,  # type: str
    py27,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
    py38,  # type: PythonInterpreter
):
    # type: (...) -> None

    assert (
        expected(
            requires_python,
            PythonBinaryName(name="python", version=(2, 7)),
            PythonBinaryName(name="python", version=(3, 10)),
            PythonBinaryName(name="python", version=(3, 8)),
        )
        == calculate_binary_names(targets=Targets(interpreters=(py27, py310, py38)))
    )


def test_calculate_no_targets_ics(requires_python):
    # type: (str) -> None

    assert (
        expected(
            requires_python,
            PythonBinaryName(name="python", version=(3, 7)),
            PythonBinaryName(name="pypy", version=(3, 7)),
            PythonBinaryName(name="python", version=(3, 8)),
            PythonBinaryName(name="pypy", version=(3, 8)),
            PythonBinaryName(name="python", version=(3, 9)),
            PythonBinaryName(name="pypy", version=(3, 9)),
            PythonBinaryName(name="pypy", version=(3, 6)),
        )
        == calculate_binary_names(interpreter_constraints=[">=3.7,<3.10", "PyPy==3.6.*"])
    )


def test_calculate_mixed(
    requires_python,  # type: str
    py27,  # type: PythonInterpreter
):
    # type: (...) -> None

    assert expected(
        requires_python,
        PythonBinaryName(name="python", version=(2, 7)),
        PythonBinaryName(name="pypy", version=(3, 8)),
        PythonBinaryName(name="python", version=(3, 6)),
        PythonBinaryName(name="pypy", version=(3, 7)),
    ) == calculate_binary_names(
        targets=Targets(
            interpreters=(py27,),
            complete_platforms=(
                CompletePlatform.create(
                    marker_environment=MarkerEnvironment(
                        platform_python_implementation="PyPy", python_version="3.8"
                    ),
                    # N.B.: Unused by the code under test, but we need to supply at least 1 tag.
                    supported_tags=CompatibilityTags.from_strings(("py3-none-any",)),
                ),
            ),
        ),
        interpreter_constraints=["CPython==3.6.*", "PyPy>=3.7,<3.9"],
    )
