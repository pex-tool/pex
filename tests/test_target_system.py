# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.resolve.target_system import MarkerEnv, UniversalTarget
from pex.third_party.packaging.markers import Marker
from pex.third_party.packaging.specifiers import SpecifierSet


def test_marker_env_extra_normalization():
    # type: () -> None

    marker_env = MarkerEnv.create(extras=("TESTS", "other_things"))

    assert marker_env.evaluate(Marker("extra == 'tests'"))

    assert not marker_env.evaluate(Marker("extra == 'test'"))
    assert marker_env.evaluate(Marker("extra != 'test'"))

    assert marker_env.evaluate(Marker("extra == 'other.things'"))
    assert marker_env.evaluate(Marker("extra == 'other-things'"))
    assert marker_env.evaluate(Marker("extra == 'Other_Things'"))

    assert not marker_env.evaluate(Marker("extra == 'OtherThings'"))
    assert marker_env.evaluate(Marker("extra != 'OtherThings'"))


def test_marker_env_version_comparison():
    # type: () -> None

    marker_env = MarkerEnv.create(
        extras=(),
        universal_target=UniversalTarget(requires_python=tuple([SpecifierSet(">=3.10,<3.14")])),
    )

    assert marker_env.evaluate(Marker("python_version ~= '3.12'"))
    assert not marker_env.evaluate(Marker("python_version ~= '3.14'"))

    assert marker_env.evaluate(Marker("python_version == '3.12'"))
    assert marker_env.evaluate(Marker("python_version != '3.14'"))
    assert marker_env.evaluate(Marker("'3.12' == python_version"))
    assert marker_env.evaluate(Marker("'3.14' != python_version"))

    assert marker_env.evaluate(Marker("python_version >= '3.9'"))
    assert not marker_env.evaluate(Marker("python_version < '3.10'"))
    assert marker_env.evaluate(Marker("'3.9' <= python_version"))
    assert not marker_env.evaluate(Marker("'3.10' > python_version"))

    assert marker_env.evaluate(Marker("python_full_version == '3.12.*'"))
    assert not marker_env.evaluate(Marker("python_full_version == '3.14.*'"))
    assert marker_env.evaluate(Marker("python_full_version == '3.11.*'"))
    assert marker_env.evaluate(Marker("'3.12.*' == python_full_version"))
    assert not marker_env.evaluate(Marker("'3.14.*' == python_full_version"))
    assert marker_env.evaluate(Marker("'3.11.*' == python_full_version"))


def test_marker_env_grouping():
    # type: () -> None

    marker_env = MarkerEnv.create(
        extras=("tests", "docs"),
        universal_target=UniversalTarget(requires_python=tuple([SpecifierSet(">=3.13")])),
    )

    assert marker_env.evaluate(
        Marker(
            "(extra == 'tests' or extra == 'tools') and ("
            "   platform_system != 'Linux' and platform_system != 'Windows' and ("
            "       python_version == '2.7' or python_full_version == '3.13.*'"
            "   )"
            ")"
        )
    )
    assert not marker_env.evaluate(
        Marker(
            "(extra == 'tests' or extra == 'tools') and ("
            "   platform_system != 'Linux' and platform_system != 'Windows' and ("
            "       python_version == '2.7' and python_full_version == '3.13.*'"
            "   )"
            ")"
        )
    )
