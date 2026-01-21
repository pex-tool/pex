# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os

from pex.interpreter_implementation import InterpreterImplementation
from pex.resolve.target_system import UniversalTarget

# N.B.: The following environment variables are used by the Pex runtime to control Pip and must be
# kept in-sync with `locker.py`.
target_systems_file = os.environ.pop("_PEX_UNIVERSAL_TARGET_FILE")
with open(target_systems_file) as fp:
    universal_target = UniversalTarget.from_dict(json.load(fp))


def patch_marker_evaluate():
    from pip._vendor.packaging import markers

    from pex.pep_503 import ProjectName
    from pex.sorted_tuple import SortedTuple
    from pex.third_party import attr

    no_extras_marker_env = universal_target.marker_env()

    def evaluate(self, environment=None):
        extra = environment.get("extra") if environment else None
        if extra:
            return attr.evolve(
                no_extras_marker_env, extras=SortedTuple([ProjectName(extra).normalized])
            ).evaluate(self)
        return no_extras_marker_env.evaluate(self)

    markers.Marker.evaluate = evaluate


def patch_wheel_model():
    from pip._internal.models.wheel import Wheel

    from pex.interpreter_constraints import iter_compatible_versions
    from pex.resolve.target_system import TargetSystem

    python_versions = sorted(
        set(version[:2] for version in iter_compatible_versions(universal_target.requires_python))
    )
    python_majors = sorted(set(version[0] for version in python_versions))

    Wheel.support_index_min = lambda *args, **kwargs: 0

    # N.B.: Pip 25.1 updated the Wheel model, removing pyversions, abis and plats and replacing
    # these with a set of file-tags Tag objects. We unify with these helpers.

    def get_abi_info(self):
        if not hasattr(self, "is_abi3"):
            abis = (
                set(self.abis)
                if hasattr(self, "abis")
                else {file_tag.abi for file_tag in self.file_tags}
            )
            self.is_abi3 = {"abi3"} == abis
            self.is_abi_none = {"none"} == abis
        return self.is_abi3, self.is_abi_none

    def get_py_versions_info(self):
        if not hasattr(self, "pyversions_info"):
            pyversions_info = []
            for file_tag in self.file_tags:
                # For the format, see: https://peps.python.org/pep-0425/#python-tag
                match = re.search(
                    r"^(?P<impl>\D{2,})(?P<major>\d)(?P<minor>\d+)?", file_tag.interpreter
                )
                if not match:
                    continue
                impl = match.group("impl")
                major = int(match.group("major"))
                minor = match.group("minor")
                pyversions_info.append((impl, major, minor))
            self.pyversions_info = tuple(pyversions_info)
        return self.pyversions_info

    def get_platforms(self):
        if hasattr(self, "plats"):
            return self.plats
        return tuple(file_tag.platform for file_tag in self.file_tags)

    supported_checks = [lambda *args, **kwargs: True]
    if python_versions:
        import re

        def supported_version(self, *_args, **_kwargs):
            if not hasattr(self, "_versions"):
                versions = set()
                is_abi3, is_abi_none = get_abi_info(self)
                for impl, major, minor in get_py_versions_info(self):
                    if impl not in ("py", "cp", "cpython", "pp", "pypy"):
                        continue

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

    if universal_target.systems and set(universal_target.systems) != set(TargetSystem.values()):
        import re

        # See: https://peps.python.org/pep-0425/#platform-tag for more about the wheel platform tag.
        platform_tag_substrings = []
        for system in universal_target.systems:
            if system is TargetSystem.LINUX:
                platform_tag_substrings.append("linux")
            elif system is TargetSystem.MAC:
                platform_tag_substrings.append("macosx")
            elif system is TargetSystem.WINDOWS:
                platform_tag_substrings.append("win")

        def supported_os_tag(self, *_args, **_kwargs):
            platforms = get_platforms(self)
            if any(plat == "any" for plat in platforms):
                return True
            for platform_tag_substring in platform_tag_substrings:
                if any((platform_tag_substring in plat) for plat in platforms):
                    return True
            return False

        supported_checks.append(supported_os_tag)

    platform_machine_values = universal_target.extra_markers.get_values("platform_machine")
    if platform_machine_values:
        import re

        # See: https://peps.python.org/pep-0425/#platform-tag for more about the wheel platform tag.
        platform_machine_regexps = tuple(
            re.compile(re.escape(machine), flags=re.IGNORECASE)
            for machine in platform_machine_values
        )

        def supported_machine_tag(self, *_args, **_kwargs):
            platforms = get_platforms(self)

            if any(plat == "any" for plat in platforms):
                return True

            if platform_machine_values.inclusive:
                for platform_machine_regexp in platform_machine_regexps:
                    if any(platform_machine_regexp.search(plat) for plat in platforms):
                        return True
                return False

            if all(
                all(platform_machine_regexp.search(plat) for plat in platforms)
                for platform_machine_regexp in platform_machine_regexps
            ):
                return False

            return True

        supported_checks.append(supported_machine_tag)

    if universal_target.implementation:

        def supported_impl(self, *_args, **_kwargs):
            for impl, _, _ in get_py_versions_info(self):
                if impl == "py":
                    return True

                if (
                    universal_target.implementation is InterpreterImplementation.CPYTHON
                    and impl in ("cp", "cpython")
                ):
                    return True

                if universal_target.implementation is InterpreterImplementation.PYPY and impl in (
                    "pp",
                    "pypy",
                ):
                    return True
            return False

        supported_checks.append(supported_impl)

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
