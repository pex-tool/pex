# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pex.bin import sh_boot
from pex.bin.sh_boot import PythonBinaryName
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.pep_425 import CompatibilityTags
from pex.pep_508 import MarkerEnvironment
from pex.platforms import Platform
from pex.targets import CompletePlatform, Targets
from pex.testing import WheelBuilder
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, List

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Calculator(object):
    pex_dist = attr.ib()  # type: str

    def calculate_binary_names(
        self,
        targets=Targets(),  # type: Targets
        interpreter_constraints=(),  # type: Iterable[str]
    ):
        return list(
            sh_boot._calculate_applicable_binary_names(
                targets=targets,
                interpreter_constraints=interpreter_constraints,
                pex_dist=self.pex_dist,
            )
        )


@pytest.fixture(scope="module")
def calculator(pex_project_dir):
    # type: (...) -> Calculator
    pex_dist = WheelBuilder(pex_project_dir).bdist()
    return Calculator(pex_dist=pex_dist)


def expected(*names):
    # type: (*PythonBinaryName) -> List[str]

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
    all_names.update(
        [
            "python3.10",
            "python3.9",
            "python3.8",
            "python3.7",
            "python3.6",
            "python3.5",
            "python2.7",
            "pypy3.10",
            "pypy3.9",
            "pypy3.8",
            "pypy3.7",
            "pypy3.6",
            "pypy3.5",
            "pypy2.7",
        ]
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


def test_calculate_no_targets_no_ics(calculator):
    # type: (Calculator) -> None

    assert expected() == calculator.calculate_binary_names()


def test_calculate_platforms_no_ics(calculator):
    # type: (Calculator) -> None

    assert expected(
        PythonBinaryName(name="python", version=(3, 6)),
        PythonBinaryName(name="pypy", version=(2, 7)),
    ) == calculator.calculate_binary_names(
        Targets(
            platforms=(
                Platform.create("macosx-10.13-x86_64-cp-36-cp36m"),
                Platform.create("linux-x86_64-pp-27-pypy_73"),
            )
        )
    )


def test_calculate_interpreters_no_ics(
    calculator,  # type: Calculator
    py27,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
    py37,  # type: PythonInterpreter
):
    # type: (...) -> None

    assert (
        expected(
            PythonBinaryName(name="python", version=(2, 7)),
            PythonBinaryName(name="python", version=(3, 10)),
            PythonBinaryName(name="python", version=(3, 7)),
        )
        == calculator.calculate_binary_names(targets=Targets(interpreters=(py27, py310, py37)))
    )


def test_calculate_no_targets_ics(calculator):
    # type: (Calculator) -> None

    assert (
        expected(
            PythonBinaryName(name="python", version=(3, 7)),
            PythonBinaryName(name="python", version=(3, 8)),
            PythonBinaryName(name="python", version=(3, 9)),
            PythonBinaryName(name="pypy", version=(3, 7)),
        )
        == calculator.calculate_binary_names(interpreter_constraints=[">=3.7,<3.10", "PyPy==3.7.*"])
    )


def test_calculate_mixed(
    calculator,  # type: Calculator
    py27,  # type: PythonInterpreter
):
    # type: (...) -> None

    assert expected(
        PythonBinaryName(name="python", version=(2, 7)),
        PythonBinaryName(name="pypy", version=(3, 8)),
        PythonBinaryName(name="python", version=(3, 6)),
        PythonBinaryName(name="pypy", version=(3, 7)),
    ) == calculator.calculate_binary_names(
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
