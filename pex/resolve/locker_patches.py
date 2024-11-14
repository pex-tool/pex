# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

try:
    from . import requires_python  # type:ignore[attr-defined] # This file will be relocated.

    python_full_versions = requires_python.PYTHON_FULL_VERSIONS
    python_versions = requires_python.PYTHON_VERSIONS
    python_majors = sorted(set(version[0] for version in python_full_versions))
except ImportError:
    python_full_versions = []
    python_versions = []
    python_majors = []

os_names = []
platform_systems = []
sys_platforms = []
platform_tag_regexps = []

# N.B.: The following environment variables are used by the Pex runtime to control Pip and must be
# kept in-sync with `locker.py`.
target_systems_file = os.environ.pop("_PEX_TARGET_SYSTEMS_FILE", None)

if target_systems_file:
    import json

    with open(target_systems_file) as fp:
        target_systems = json.load(fp)
    os_names = target_systems["os_names"]
    platform_systems = target_systems["platform_systems"]
    sys_platforms = target_systems["sys_platforms"]
    platform_tag_regexps = target_systems["platform_tag_regexps"]


def patch_marker_evaluate():
    from pip._vendor.packaging import markers  # type: ignore[import]

    from pex.exceptions import production_assert
    from pex.typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from typing import Any, Callable, Dict, Iterable, List, Tuple, Type

    original_eval_op = markers._eval_op

    # N.B.: The `packaging` distribution vendored with Pip>=24.1 has a patch that tests the
    # `python_full_version` marker environment value to see if it ends with "+", in which case it
    # appends "local" to it (see: https://github.com/pypa/packaging/pull/802). We support this test
    # by ensuring our value for `python_full_version`, either a `skip` sentinel or a list value,
    # both support the `endswith(value)` test and always return `False`.
    class NeverEndsWithMixin(object):
        def endswith(self, _):
            # type: (str) -> bool
            return False

    skip = NeverEndsWithMixin()

    class EndsWithList(NeverEndsWithMixin, list):
        pass

    def versions_to_string(
        versions,  # type: Iterable[Tuple[int, ...]]
        version_modifier=lambda version: version,  # type: Callable[[str], str]
        list_type=list,  # type: Type[List]
    ):
        # type: (...) -> List[str]
        return list_type(version_modifier(".".join(map(str, version))) for version in versions)

    original_extra = markers.default_environment().get("extra")
    python_versions_strings = versions_to_string(python_versions) or skip
    python_full_versions_strings = (
        versions_to_string(
            python_full_versions,
            # N.B.: We replicate the logic `packaging` vendored with Pip>=24.1 has for dealing with
            # non-tagged CPython builds, which is fine to apply across all versions of Pip and its
            # vendored packaging that we support.
            version_modifier=lambda version: (
                version + "local" if version.endswith("+") else version
            ),
            list_type=EndsWithList,
        )
        or skip
    )
    os_names_strings = os_names or skip
    platform_systems_strings = platform_systems or skip
    sys_platforms_strings = sys_platforms or skip

    class EvaluationEnvironment(dict):
        @classmethod
        def get_env(
            cls,
            environment,  # type: Dict[Any, Any]
            name,  # type: Any
        ):
            # type: (...) -> Any
            production_assert(
                isinstance(environment, cls),
                "Expected environment to come from the {function} function, "
                "which we patch to return {expected_type}, but was {actual_type}",
                function=markers.default_environment,
                expected_type=cls,
                actual_type=type(environment),
            )
            return environment[name]

        def __missing__(self, name):
            # type: (Any) -> Any
            if name == "extra":
                if original_extra is None:
                    raise markers.UndefinedEnvironmentName(
                        "'extra' does not exist in evaluation environment."
                    )
                return original_extra
            if name == "python_version":
                return python_versions_strings
            if name == "python_full_version":
                return python_full_versions_strings
            if name == "os_name":
                return os_names_strings
            if name == "platform_system":
                return platform_systems_strings
            if name == "sys_platform":
                return sys_platforms_strings
            return skip

    def _eval_op(
        lhs,  # type: Any
        op,  # type: Any
        rhs,  # type: Any
    ):
        # type: (...) -> bool
        if lhs is skip or rhs is skip:
            return True
        return any(
            original_eval_op(left, op, right)
            for left in (lhs if isinstance(lhs, list) else [lhs])
            for right in (rhs if isinstance(rhs, list) else [rhs])
        )

    # Works with all Pip vendored packaging distributions.
    markers.default_environment = EvaluationEnvironment
    # Covers Pip<24.1 vendored packaging.
    markers._get_env = EvaluationEnvironment.get_env

    markers._eval_op = _eval_op


def patch_wheel_model():
    from pip._internal.models.wheel import Wheel  # type: ignore[import]

    Wheel.support_index_min = lambda *args, **kwargs: 0

    supported_checks = [lambda *args, **kwargs: True]
    if python_versions:
        import re

        def supported_version(self, *_args, **_kwargs):
            if not hasattr(self, "_versions"):
                versions = set()
                abis = list(self.abis)
                is_abi3 = ["abi3"] == abis
                is_abi_none = ["none"] == abis
                for pyversion in self.pyversions:
                    # For the format, see: https://peps.python.org/pep-0425/#python-tag
                    match = re.search(r"^(?P<impl>\D{2,})(?P<major>\d)(?P<minor>\d+)?", pyversion)
                    if not match:
                        continue

                    impl = match.group("impl")
                    if impl not in ("cp", "pp", "py", "cpython", "pypy"):
                        continue

                    major = int(match.group("major"))
                    minor = match.group("minor")
                    if is_abi_none or (is_abi3 and major == 3):
                        versions.add(major)
                    elif minor:
                        versions.add((major, int(minor)))
                    else:
                        versions.add(major)

                self._versions = versions

            return any(
                (version in python_majors) or (version in python_versions)
                for version in self._versions
            )

        supported_checks.append(supported_version)

    if platform_tag_regexps:
        import re

        def supported_platform_tag(self, *_args, **_kwargs):
            if any(plat == "any" for plat in self.plats):
                return True
            for platform_tag_regexp in platform_tag_regexps:
                if any(re.search(platform_tag_regexp, plat) for plat in self.plats):
                    return True
            return False

        supported_checks.append(supported_platform_tag)

    Wheel.supported = lambda *args, **kwargs: all(
        check(*args, **kwargs) for check in supported_checks
    )

    # N.B.: This patch is a noop for the 20.3.4-patched Pip but is required in newer Pip.
    # The method is used as a speedup hack by newer Pip in some cases instead of
    # Wheel.support_index_min.
    Wheel.find_most_preferred_tag = lambda *args, **kwargs: 0


def patch():
    # 1.) Universal dependency environment marker applicability.
    #
    # Allows all dependencies in metadata to be followed regardless
    # of whether they apply to this system. For example, if this is
    # Python 3.10 but a marker says a dependency is only for
    # 'python_version < "3.6"' we still want to lock that dependency
    # subgraph too.
    patch_marker_evaluate()

    # 2.) Universal wheel tag applicability.
    #
    # Allows all wheel URLs to be checked even when the wheel does not
    # match system tags.
    patch_wheel_model()
