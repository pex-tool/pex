# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import os
import platform
from collections import defaultdict

from pex.enum import Enum
from pex.platforms import Platform
from pex.targets import Targets
from pex.third_party.packaging import tags  # noqa
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import DefaultDict, Iterable, Optional, Set, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class ScieStyle(Enum["ScieStyle.Value"]):
    class Value(Enum.Value):
        pass

    LAZY = Value("lazy")
    EAGER = Value("eager")


class SciePlatform(Enum["SciePlatform.Value"]):
    class Value(Enum.Value):
        @property
        def extension(self):
            # type: () -> str
            return (
                ".exe"
                if self in (SciePlatform.WINDOWS_AARCH64, SciePlatform.WINDOWS_X86_64)
                else ""
            )

        def binary_name(self, binary_name):
            # type: (str) -> str
            return "{binary_name}{extension}".format(
                binary_name=binary_name, extension=self.extension
            )

        def qualified_binary_name(self, binary_name):
            # type: (str) -> str
            return "{binary_name}-{platform}{extension}".format(
                binary_name=binary_name, platform=self, extension=self.extension
            )

        def qualified_file_name(self, file_name):
            # type: (str) -> str
            stem, ext = os.path.splitext(file_name)
            return "{stem}-{platform}{ext}".format(stem=stem, platform=self, ext=ext)

    LINUX_AARCH64 = Value("linux-aarch64")
    LINUX_X86_64 = Value("linux-x86_64")
    MACOS_AARCH64 = Value("macos-aarch64")
    MACOS_X86_64 = Value("macos-x86_64")
    WINDOWS_AARCH64 = Value("windows-x86_64")
    WINDOWS_X86_64 = Value("windows-aarch64")

    @classmethod
    def parse(cls, value):
        # type: (str) -> SciePlatform.Value
        return cls.current() if "current" == value else cls.for_value(value)

    @classmethod
    def current(cls):
        # type: () -> SciePlatform.Value
        system = platform.system().lower()
        machine = platform.machine().lower()
        if "linux" == system:
            if machine in ("aarch64", "arm64"):
                return cls.LINUX_AARCH64
            elif machine in ("amd64", "x86_64"):
                return cls.LINUX_X86_64
        elif "darwin" == system:
            if machine in ("aarch64", "arm64"):
                return cls.MACOS_AARCH64
            elif machine in ("amd64", "x86_64"):
                return cls.MACOS_X86_64
        elif "windows" == system:
            if machine in ("aarch64", "arm64"):
                return cls.WINDOWS_AARCH64
            elif machine in ("amd64", "x86_64"):
                return cls.WINDOWS_X86_64
        raise ValueError(
            "The current operating system / machine pair is not supported!: "
            "{system} / {machine}".format(system=system, machine=machine)
        )


@attr.s(frozen=True)
class ScieTarget(object):
    platform = attr.ib()  # type: SciePlatform.Value
    python_version = attr.ib()  # type: Union[Tuple[int, int], Tuple[int, int, int]]
    pbs_release = attr.ib(default=None)  # type: Optional[str]

    @property
    def version_str(self):
        # type: () -> str
        return ".".join(map(str, self.python_version))


@attr.s(frozen=True)
class ScieInfo(object):
    style = attr.ib()  # type: ScieStyle.Value
    target = attr.ib()  # type: ScieTarget
    file = attr.ib()  # type: str

    @property
    def platform(self):
        # type: () -> SciePlatform.Value
        return self.target.platform

    @property
    def python_version(self):
        # type: () -> Union[Tuple[int, int], Tuple[int, int, int]]
        return self.target.python_version


@attr.s(frozen=True)
class ScieOptions(object):
    style = attr.ib(default=ScieStyle.LAZY)  # type: ScieStyle.Value
    platforms = attr.ib(default=())  # type: Tuple[SciePlatform.Value, ...]
    pbs_release = attr.ib(default=None)  # type: Optional[str]
    python_version = attr.ib(
        default=None
    )  # type: Optional[Union[Tuple[int, int], Tuple[int, int, int]]]

    def create_configuration(self, targets):
        # type: (Targets) -> ScieConfiguration
        return ScieConfiguration.from_targets(self, targets)


@attr.s(frozen=True)
class ScieConfiguration(object):
    @classmethod
    def from_tags(
        cls,
        options,  # type: ScieOptions
        tags,  # type: Iterable[tags.Tag]
    ):
        # type: (...) -> ScieConfiguration
        return cls._from_platforms(
            options=options, platforms=tuple(Platform.from_tag(tag) for tag in tags)
        )

    @classmethod
    def from_targets(
        cls,
        options,  # type: ScieOptions
        targets,  # type: Targets
    ):
        # type: (...) -> ScieConfiguration
        return cls._from_platforms(
            options=options,
            platforms=tuple(target.platform for target in targets.unique_targets()),
        )

    @classmethod
    def _from_platforms(
        cls,
        options,  # type: ScieOptions
        platforms,  # type: Iterable[Platform]
    ):
        # type: (...) -> ScieConfiguration

        python_version = options.python_version
        python_versions_by_platform = defaultdict(
            set
        )  # type: DefaultDict[SciePlatform.Value, Set[Union[Tuple[int, int], Tuple[int, int, int]]]]
        for plat in platforms:
            if python_version:
                plat_python_version = python_version
            elif len(plat.version_info) < 2:
                continue
            else:
                plat_python_version = cast(
                    "Union[Tuple[int, int], Tuple[int, int, int]]", plat.version_info
                )

            # We use Python Build Standalone to create scies, and we know it does not support
            # CPython<3.8.
            if plat_python_version < (3, 8):
                continue

            # We use Python Build Standalone to create scies, and we know it only provides CPython
            # interpreters.
            if plat.impl not in ("py", "cp"):
                continue

            platform_str = plat.platform
            is_aarch64 = "arm64" in platform_str or "aarch64" in platform_str
            is_x86_64 = "amd64" in platform_str or "x86_64" in platform_str
            if not is_aarch64 ^ is_x86_64:
                continue

            if "linux" in platform_str:
                scie_platform = (
                    SciePlatform.LINUX_AARCH64 if is_aarch64 else SciePlatform.LINUX_X86_64
                )
            elif "mac" in platform_str:
                scie_platform = (
                    SciePlatform.MACOS_AARCH64 if is_aarch64 else SciePlatform.MACOS_X86_64
                )
            elif "win" in platform_str:
                scie_platform = (
                    SciePlatform.WINDOWS_AARCH64 if is_aarch64 else SciePlatform.WINDOWS_X86_64
                )
            else:
                continue

            python_versions_by_platform[scie_platform].add(plat_python_version)

        for explicit_platform in options.platforms:
            if explicit_platform not in python_versions_by_platform:
                if options.python_version:
                    python_versions_by_platform[explicit_platform] = {options.python_version}
                else:
                    python_versions_by_platform[explicit_platform] = set(
                        itertools.chain.from_iterable(python_versions_by_platform.values())
                    )
        if options.platforms:
            for configured_platform in tuple(python_versions_by_platform):
                if configured_platform not in options.platforms:
                    python_versions_by_platform.pop(configured_platform, None)

        scie_targets = tuple(
            ScieTarget(
                platform=scie_platform,
                pbs_release=options.pbs_release,
                python_version=max(python_versions),
            )
            for scie_platform, python_versions in sorted(python_versions_by_platform.items())
        )
        return cls(options=options, targets=tuple(scie_targets))

    options = attr.ib()  # type: ScieOptions
    targets = attr.ib()  # type: Tuple[ScieTarget, ...]

    def __len__(self):
        # type: () -> int
        return len(self.targets)
