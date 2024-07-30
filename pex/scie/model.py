# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import os
import platform
from collections import OrderedDict, defaultdict

from pex.dist_metadata import Distribution, NamedEntryPoint
from pex.enum import Enum
from pex.finders import get_entry_point_from_console_script
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.platforms import Platform
from pex.targets import Targets
from pex.third_party.packaging import tags  # noqa
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import DefaultDict, Iterable, Iterator, List, Optional, Set, Text, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class ScieStyle(Enum["ScieStyle.Value"]):
    class Value(Enum.Value):
        pass

    LAZY = Value("lazy")
    EAGER = Value("eager")


@attr.s(frozen=True)
class ConsoleScript(object):
    name = attr.ib()  # type: str
    project_name = attr.ib(default=None)  # type: Optional[ProjectName]


@attr.s(frozen=True)
class ConsoleScriptsManifest(object):
    @classmethod
    def try_parse(cls, value):
        # type: (str) -> Optional[ConsoleScriptsManifest]
        script_name, sep, project_name = value.partition("@")
        if not sep and all(script_name.partition("=")):
            # This is an ad-hoc entrypoint; not a console script specification.
            return None

        if sep and not script_name and not project_name:
            return cls(add_all=True)
        elif script_name and script_name != "!":
            if script_name.startswith("!"):
                return cls(
                    remove_individual=(
                        ConsoleScript(
                            name=script_name[1:],
                            project_name=ProjectName(project_name) if project_name else None,
                        ),
                    )
                )
            else:
                return cls(
                    add_individual=(
                        ConsoleScript(
                            name=script_name,
                            project_name=ProjectName(project_name) if project_name else None,
                        ),
                    )
                )
        elif sep and project_name and (not script_name or script_name == "!"):
            if script_name == "!":
                return cls(remove_project=(ProjectName(project_name),))
            else:
                return cls(add_project=(ProjectName(project_name),))
        else:
            return None

    add_individual = attr.ib(default=())  # type: Tuple[ConsoleScript, ...]
    remove_individual = attr.ib(default=())  # type: Tuple[ConsoleScript, ...]
    add_project = attr.ib(default=())  # type: Tuple[ProjectName, ...]
    remove_project = attr.ib(default=())  # type: Tuple[ProjectName, ...]
    add_all = attr.ib(default=False)  # type: bool

    def iter_specs(self):
        # type: () -> Iterator[Text]
        if self.add_all:
            yield "@"
        for project_name in self.add_project:
            yield "@{dist}".format(dist=project_name.raw)
        for script in self.add_individual:
            if script.project_name:
                yield "{script_name}@{project_name}".format(
                    script_name=script.name, project_name=script.project_name.raw
                )
            else:
                yield script.name
        for project_name in self.remove_project:
            yield "!@{dist}".format(dist=project_name.raw)
        for script in self.remove_individual:
            if script.project_name:
                yield "!{script_name}@{project_name}".format(
                    script_name=script.name, project_name=script.project_name.raw
                )
            else:
                yield "!{script}".format(script=script.name)

    def merge(self, other):
        # type: (ConsoleScriptsManifest) -> ConsoleScriptsManifest
        return ConsoleScriptsManifest(
            add_individual=self.add_individual + other.add_individual,
            remove_individual=self.remove_individual + other.remove_individual,
            add_project=self.add_project + other.add_project,
            remove_project=self.remove_project + other.remove_project,
            add_all=self.add_all or other.add_all,
        )

    def collect(self, pex):
        # type: (PEX) -> Iterable[NamedEntryPoint]

        dists = tuple(
            fingerprinted_distribution.distribution
            for fingerprinted_distribution in pex.iter_distributions()
        )

        console_scripts = OrderedDict(
            (console_script, None) for console_script in self.add_individual
        )  # type: OrderedDict[ConsoleScript, Optional[NamedEntryPoint]]

        if self.add_project or self.remove_project or self.add_all:
            for dist in dists:
                remove = dist.metadata.project_name in self.remove_project
                add = self.add_all or dist.metadata.project_name in self.add_project
                if not remove and not add:
                    continue
                for name, named_entry_point in (
                    dist.get_entry_map().get("console_scripts", {}).items()
                ):
                    if remove:
                        console_scripts.pop(ConsoleScript(name=name), None)
                        console_scripts.pop(
                            ConsoleScript(name=name, project_name=dist.metadata.project_name), None
                        )
                    else:
                        console_scripts[
                            ConsoleScript(name=name, project_name=dist.metadata.project_name)
                        ] = named_entry_point

        for console_script in self.remove_individual:
            console_scripts.pop(console_script, None)
            if not console_script.project_name:
                for cs in tuple(console_scripts):
                    if console_script.name == cs.name:
                        console_scripts.pop(cs)

        def iter_entry_points():
            # type: () -> Iterator[NamedEntryPoint]
            not_found = []  # type: List[ConsoleScript]
            wrong_project = []  # type: List[Tuple[ConsoleScript, Distribution]]
            for script, ep in console_scripts.items():
                if ep:
                    yield ep
                else:
                    dist_entry_point = get_entry_point_from_console_script(script.name, dists)
                    if not dist_entry_point:
                        not_found.append(script)
                    elif (
                        script.project_name
                        and dist_entry_point.dist.metadata.project_name != script.project_name
                    ):
                        wrong_project.append((script, dist_entry_point.dist))
                    else:
                        yield NamedEntryPoint(
                            name=dist_entry_point.name, entry_point=dist_entry_point.entry_point
                        )

            if not_found or wrong_project:
                raise ValueError(
                    # TODO(John Sirois): XXX: Craft an error message.
                    "not found: {not_found}\n"
                    "wrong project: {wrong_project}".format(
                        not_found=" ".join(map(str, not_found)),
                        wrong_project=" ".join(map(str, wrong_project)),
                    )
                )

        return tuple(iter_entry_points())


@attr.s(frozen=True)
class BusyBoxEntryPoints(object):
    console_scripts_manifest = attr.ib()  # type: ConsoleScriptsManifest
    ad_hoc_entry_points = attr.ib()  # type: Tuple[NamedEntryPoint, ...]


class _CurrentPlatform(object):
    def __get__(self, obj, objtype=None):
        # type: (...) -> SciePlatform.Value
        if not hasattr(self, "_current"):
            system = platform.system().lower()
            machine = platform.machine().lower()
            if "linux" == system:
                if machine in ("aarch64", "arm64"):
                    self._current = SciePlatform.LINUX_AARCH64
                elif machine in ("amd64", "x86_64"):
                    self._current = SciePlatform.LINUX_X86_64
            elif "darwin" == system:
                if machine in ("aarch64", "arm64"):
                    self._current = SciePlatform.MACOS_AARCH64
                elif machine in ("amd64", "x86_64"):
                    self._current = SciePlatform.MACOS_X86_64
            elif "windows" == system:
                if machine in ("aarch64", "arm64"):
                    self._current = SciePlatform.WINDOWS_AARCH64
                elif machine in ("amd64", "x86_64"):
                    self._current = SciePlatform.WINDOWS_X86_64
            if not hasattr(self, "_current"):
                raise ValueError(
                    "The current operating system / machine pair is not supported!: "
                    "{system} / {machine}".format(system=system, machine=machine)
                )
        return self._current


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
    CURRENT = _CurrentPlatform()

    @classmethod
    def parse(cls, value):
        # type: (str) -> SciePlatform.Value
        return cls.CURRENT if "current" == value else cls.for_value(value)


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
    busybox_entrypoints = attr.ib(default=None)  # type: Optional[BusyBoxEntryPoints]
    platforms = attr.ib(default=())  # type: Tuple[SciePlatform.Value, ...]
    pbs_release = attr.ib(default=None)  # type: Optional[str]
    python_version = attr.ib(
        default=None
    )  # type: Optional[Union[Tuple[int, int], Tuple[int, int, int]]]
    science_binary_url = attr.ib(default=None)  # type: Optional[str]

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
                # Here were guessing an available PBS CPython version. Since a triple is unlikely to
                # hit, we just use major / minor. If the user wants control they can specify
                # options.python_version via `--scie-python-version`.
                plat_python_version = cast(
                    "Union[Tuple[int, int], Tuple[int, int, int]]", plat.version_info
                )[:2]

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
