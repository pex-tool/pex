# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.pep_508 import MarkerEnvironment
from pex.platforms import PlatformSpec
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Tuple, Union


def test_marker_env_from_platform():
    # type: () -> None

    def assert_marker_env(
        platform_spec,  # type: str
        python_version,  # type: Union[Tuple[int, int], Tuple[int, int, int]]
        implementation_name="cpython",  # type: str
        platform_python_implementation="CPython",  # type: str
    ):
        # type: (...) -> None

        marker_env = MarkerEnvironment.from_platform(PlatformSpec.parse(platform_spec))
        assert marker_env.implementation_name == implementation_name
        assert marker_env.implementation_version is None
        assert marker_env.os_name == "posix"
        assert marker_env.platform_machine == "x86_64"
        assert marker_env.platform_python_implementation == platform_python_implementation
        assert marker_env.platform_release is None
        assert marker_env.platform_system == "Linux"
        assert marker_env.platform_version is None
        assert marker_env.python_full_version == (
            ".".join(map(str, python_version)) if len(python_version) == 3 else None
        )
        assert marker_env.python_version == ".".join(map(str, python_version[:2]))
        assert marker_env.sys_platform == "linux"

    assert_marker_env("linux_x86_64-cp-39-cp39", (3, 9))
    assert_marker_env("linux_x86_64-cp-3.9.25-cp39", (3, 9, 25))
    assert_marker_env("linux_x86_64-cp-3.14.15-cp314t", (3, 14, 15))
    assert_marker_env(
        "linux-x86_64-pp-311-pypy311_pp73",
        (3, 11),
        implementation_name="pypy",
        platform_python_implementation="PyPy",
    )
