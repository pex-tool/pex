# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import re

import pytest

from pex import targets
from pex.dist_metadata import Requirement
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.pep_425 import CompatibilityTags
from pex.pep_508 import MarkerEnvironment
from pex.platforms import Platform
from pex.resolve import abbreviated_platforms
from pex.targets import (
    AbbreviatedPlatform,
    CompletePlatform,
    LocalInterpreter,
    RequiresPythonError,
    Target,
    Targets,
)
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING
from testing import IS_PYPY, PY39, PY310, PY_VER, ensure_python_interpreter

if TYPE_CHECKING:
    from typing import Optional


def test_current(current_interpreter):
    # type: (PythonInterpreter) -> None
    assert LocalInterpreter.create() == targets.current()
    assert LocalInterpreter.create(current_interpreter) == targets.current()


def test_interpreter(
    py27,  # type: PythonInterpreter
    current_interpreter,  # type: PythonInterpreter
):
    # type: (...) -> None
    assert Targets().interpreter is None
    assert py27 == Targets(interpreters=(py27,)).interpreter
    assert py27 == Targets(interpreters=(py27, current_interpreter)).interpreter


def test_unique_targets(
    py27,  # type: PythonInterpreter
    py38,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
    current_interpreter,  # type: PythonInterpreter
    current_platform,  # type: Platform
):
    # type: (...) -> None
    assert (
        OrderedSet([targets.current()]) == Targets().unique_targets()
    ), "Expected the default TargetConfiguration to produce the current interpreter."

    assert OrderedSet([targets.current()]) == Targets(platforms=(None,)).unique_targets(), (
        "Expected the 'current' platform - which maps to `None` - to produce the current "
        "interpreter when no interpreters were configured."
    )

    assert (
        OrderedSet([LocalInterpreter.create(py27)])
        == Targets(interpreters=(py27,), platforms=(None,)).unique_targets()
    ), (
        "Expected the 'current' platform - which maps to `None` - to be ignored when at least one "
        "concrete interpreter for the current platform is configured."
    )

    assert (
        OrderedSet([AbbreviatedPlatform.create(current_platform)])
        == Targets(platforms=(current_platform,)).unique_targets()
    )

    assert (
        OrderedSet(LocalInterpreter.create(i) for i in (py27, py38, py310))
        == Targets(interpreters=(py27, py38, py310)).unique_targets()
    )

    complete_platform_current = CompletePlatform.from_interpreter(current_interpreter)
    complete_platform_py27 = CompletePlatform.from_interpreter(py27)
    assert (
        OrderedSet([complete_platform_current, complete_platform_py27])
        == Targets(
            complete_platforms=(complete_platform_current, complete_platform_py27)
        ).unique_targets()
    )


def assert_python_requirement_applies(
    expected_result,  # type: bool
    target,  # type: Target
    python_requirement,  # type: str
    source=None,  # type: Optional[Requirement]
):
    # type: (...) -> None
    assert expected_result == target.requires_python_applies(
        SpecifierSet(python_requirement), source=source or Requirement.parse("foo")
    )


def test_requires_python_current():
    # type: () -> None

    current_target = targets.current()
    major, minor, patch = current_target.interpreter.version
    patch_is_zero = 0 == patch

    def requires_python(template):
        # type: (str) -> str
        return template.format(major=major, minor=minor, patch=patch)

    def assert_requires_python(
        expected_result,  # type: bool
        template,  # type: str
    ):
        # type: (...) -> None
        assert_python_requirement_applies(
            expected_result=expected_result,
            target=current_target,
            python_requirement=requires_python(template),
        )

    assert_requires_python(True, "~={major}.{minor}")

    assert_requires_python(True, "=={major}.{minor}.*")
    assert_requires_python(patch_is_zero, "=={major}.{minor}")
    assert_requires_python(True, "=={major}.{minor}.{patch}")

    assert_requires_python(True, "!={major}")
    assert_requires_python(False, "!={major}.*")
    assert_requires_python(not patch_is_zero, "!={major}.{minor}")
    assert_requires_python(False, "!={major}.{minor}.*")
    assert_requires_python(False, "!={major}.{minor}.{patch}")

    assert_requires_python(False, "<{major}")
    assert_requires_python(False, "<={major}")
    assert_requires_python(False, "<{major}.{minor}")
    assert_requires_python(patch_is_zero, "<={major}.{minor}")
    assert_requires_python(False, "<{major}.{minor}.{patch}")
    assert_requires_python(True, "<={major}.{minor}.{patch}")

    assert_requires_python(True, ">{major}")
    assert_requires_python(True, ">={major}")
    assert_requires_python(not patch_is_zero, ">{major}.{minor}")
    assert_requires_python(True, ">={major}.{minor}")
    assert_requires_python(False, ">{major}.{minor}.{patch}")
    assert_requires_python(True, ">={major}.{minor}.{patch}")

    assert_requires_python(False, "==={major}.{minor}")
    assert_requires_python(True, "==={major}.{minor}.{patch}")


def test_requires_python_abbreviated_platform():
    abbreviated_platform = AbbreviatedPlatform.create(
        abbreviated_platforms.create("linux-x86_64-cp-37-m")
    )

    def assert_requires_python(
        expected_result,  # type: bool
        requires_python,  # type: str
    ):
        # type: (...) -> None
        assert_python_requirement_applies(
            expected_result=expected_result,
            target=abbreviated_platform,
            python_requirement=requires_python,
        )

    assert_requires_python(True, "~=3.7")

    assert_requires_python(True, "==3.7.*")
    assert_requires_python(True, "==3.7")
    assert_requires_python(True, "==3.7.0")
    assert_requires_python(False, "==3.7.1")

    assert_requires_python(True, "!=3")
    assert_requires_python(False, "!=3.*")
    assert_requires_python(False, "!=3.7")
    assert_requires_python(False, "!=3.7.*")
    assert_requires_python(False, "!=3.7.0")
    assert_requires_python(True, "!=3.7.1")

    assert_requires_python(False, "<3")
    assert_requires_python(False, "<=3")
    assert_requires_python(False, "<3.7")
    assert_requires_python(True, "<=3.7")
    assert_requires_python(False, "<3.7.0")
    assert_requires_python(True, "<3.7.1")
    assert_requires_python(True, "<=3.7.0")

    assert_requires_python(True, ">3")
    assert_requires_python(True, ">=3")
    assert_requires_python(False, ">3.7")
    assert_requires_python(True, ">=3.7")
    assert_requires_python(False, ">3.7.0")
    assert_requires_python(True, ">=3.7.0")

    assert_requires_python(True, "===3.7")

    # There is no zeo-padding for the `===` operator:
    # https://www.python.org/dev/peps/pep-0440/#arbitrary-equality
    assert_requires_python(False, "===3.7.0")

    assert_requires_python(False, "===3.7.1")


def test_requires_python_invalid_target():
    # type: () -> None

    # This target has an empty marker environment; so no `python_version` and no
    # `python_full_version`.
    invalid_target = CompletePlatform.create(
        marker_environment=MarkerEnvironment(),
        supported_tags=CompatibilityTags.from_strings(["cp37-cp37m-linux_x86_64"]),
    )

    requires_python = SpecifierSet(">=2.7")
    source = Requirement.parse("foo==1.2.3")
    with pytest.raises(
        RequiresPythonError,
        match=r".*{}.*".format(
            re.escape(
                "Encountered `Requires-Python: >=2.7` when evaluating foo==1.2.3 for applicability "
                "but the Python version information needed to evaluate this requirement is not "
                "contained in the target being evaluated for: cp37-cp37m-linux_x86_64"
            )
        ),
    ):
        invalid_target.requires_python_applies(requires_python=requires_python, source=source)


def test_from_target_local_interpreter():
    # type: () -> None

    local_interpreter = LocalInterpreter.create()
    tgts = Targets.from_target(local_interpreter)
    assert local_interpreter.interpreter == tgts.interpreter
    assert OrderedSet([local_interpreter]) == tgts.unique_targets(only_explicit=False)
    assert OrderedSet([local_interpreter]) == tgts.unique_targets(only_explicit=True)


def test_from_target_abbreviated_platform(current_platform):
    # type: (Platform) -> None

    abbreviated_platform = AbbreviatedPlatform.create(platform=current_platform)
    tgts = Targets.from_target(abbreviated_platform)
    assert tgts.interpreter is None
    assert OrderedSet([abbreviated_platform]) == tgts.unique_targets(only_explicit=False)
    assert OrderedSet([abbreviated_platform]) == tgts.unique_targets(only_explicit=True)


def test_from_target_complete_platform(current_interpreter):
    # type: (PythonInterpreter) -> None

    complete_platform = CompletePlatform.from_interpreter(current_interpreter)
    tgts = Targets.from_target(complete_platform)
    assert tgts.interpreter is None
    assert OrderedSet([complete_platform]) == tgts.unique_targets(only_explicit=False)
    assert OrderedSet([complete_platform]) == tgts.unique_targets(only_explicit=True)


def test_compatible_shebang(
    current_interpreter,  # type: PythonInterpreter
    current_platform,  # type: Platform
):
    # type: (...) -> None

    current_python = "pypy" if IS_PYPY else "python"
    current_version = ".".join(map(str, PY_VER))
    current_python_shebang = "#!/usr/bin/env {python}{version}".format(
        python=current_python, version=current_version
    )
    assert (
        current_python_shebang
        == Targets.from_target(LocalInterpreter.create(current_interpreter)).compatible_shebang()
    )
    assert (
        current_python_shebang
        == Targets.from_target(AbbreviatedPlatform.create(current_platform)).compatible_shebang()
    )
    current_complete_platform = CompletePlatform.from_interpreter(current_interpreter)
    assert (
        current_python_shebang
        == Targets.from_target(current_complete_platform).compatible_shebang()
    )
    assert (
        current_python_shebang
        == Targets(
            interpreters=(current_interpreter,),
            complete_platforms=(current_complete_platform,),
            platforms=(current_platform,),
        ).compatible_shebang()
    )

    incompatible_interpreter = PythonInterpreter.from_binary(
        ensure_python_interpreter(PY39 if PY_VER == (3, 10) else PY310)
    )
    assert (
        Targets(interpreters=(current_interpreter, incompatible_interpreter)).compatible_shebang()
        is None
    )

    incompatible_version_info = (3, 9) if PY_VER == (3, 10) else (3, 10)
    incompatible_platform_version = Platform(
        platform=current_platform.platform,
        impl=current_platform.impl,
        version_info=incompatible_version_info,
        version=".".join(map(str, incompatible_version_info)),
        abi=current_platform.abi,
        supported_tags=current_platform.supported_tags,
    )
    assert (
        Targets(platforms=(current_platform, incompatible_platform_version)).compatible_shebang()
        is None
    )

    incompatible_platform_impl = Platform(
        platform=current_platform.platform,
        impl="cp" if current_platform.impl == "pp" else "pp",
        version_info=current_platform.version_info,
        version=current_platform.version,
        abi=current_platform.abi,
        supported_tags=current_platform.supported_tags,
    )
    assert (
        Targets(platforms=(current_platform, incompatible_platform_impl)).compatible_shebang()
        is None
    )
