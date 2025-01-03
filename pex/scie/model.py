# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import os
import platform
from collections import OrderedDict, defaultdict

from pex.common import pluralize
from pex.dist_metadata import Distribution, NamedEntryPoint
from pex.enum import Enum
from pex.finders import get_entry_point_from_console_script
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.platforms import PlatformSpec
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


ScieStyle.seal()


class PlatformNamingStyle(Enum["PlatformNamingStyle.Value"]):
    class Value(Enum.Value):
        pass

    DYNAMIC = Value("dynamic")
    PARENT_DIR = Value("platform-parent-dir")
    FILE_SUFFIX = Value("platform-file-suffix")


PlatformNamingStyle.seal()


@attr.s(frozen=True)
class ConsoleScript(object):
    name = attr.ib()  # type: str
    project_name = attr.ib(default=None)  # type: Optional[ProjectName]

    def __str__(self):
        # type: () -> str
        return (
            "{script_name}@{project_name}".format(
                script_name=self.name, project_name=self.project_name.raw
            )
            if self.project_name
            else self.name
        )


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
            yield str(script)
        for project_name in self.remove_project:
            yield "!@{dist}".format(dist=project_name.raw)
        for script in self.remove_individual:
            yield "!{script}".format(script=script)

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
            not_founds = []  # type: List[ConsoleScript]
            wrong_projects = []  # type: List[Tuple[ConsoleScript, Distribution]]
            for script, ep in console_scripts.items():
                if ep:
                    yield ep
                else:
                    dist_entry_point = get_entry_point_from_console_script(script.name, dists)
                    if not dist_entry_point:
                        not_founds.append(script)
                    elif (
                        script.project_name
                        and dist_entry_point.dist.metadata.project_name != script.project_name
                    ):
                        wrong_projects.append((script, dist_entry_point.dist))
                    else:
                        yield NamedEntryPoint(
                            name=dist_entry_point.name, entry_point=dist_entry_point.entry_point
                        )

            if not_founds or wrong_projects:
                failures = []  # type: List[str]
                if not_founds:
                    failures.append(
                        "Could not find {scripts}: {script_names}".format(
                            scripts=pluralize(not_founds, "script"),
                            script_names=" ".join(map(str, not_founds)),
                        )
                    )
                if wrong_projects:
                    failures.append(
                        "Found {scripts} in the wrong {projects}:\n  {wrong_projects}".format(
                            scripts=pluralize(wrong_projects, "script"),
                            projects=pluralize(wrong_projects, "project"),
                            wrong_projects="\n  ".join(
                                "{script} found in {project}".format(
                                    script=script, project=dist.project_name
                                )
                                for script, dist in wrong_projects
                            ),
                        )
                    )
                raise ValueError(
                    "Failed to resolve some console scripts:\n+ {failures}".format(
                        failures="\n+ ".join(failures)
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
                elif machine in ("armv7l", "armv8l"):
                    self._current = SciePlatform.LINUX_ARMV7L
                elif machine == "ppc64le":
                    self._current = SciePlatform.LINUX_PPC64LE
                elif machine == "s390x":
                    self._current = SciePlatform.LINUX_S390X
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
    LINUX_ARMV7L = Value("linux-armv7l")
    LINUX_PPC64LE = Value("linux-powerpc64")
    LINUX_S390X = Value("linux-s390x")
    LINUX_X86_64 = Value("linux-x86_64")
    MACOS_AARCH64 = Value("macos-aarch64")
    MACOS_X86_64 = Value("macos-x86_64")
    WINDOWS_AARCH64 = Value("windows-aarch64")
    WINDOWS_X86_64 = Value("windows-x86_64")
    CURRENT = _CurrentPlatform()

    @classmethod
    def parse(cls, value):
        # type: (str) -> SciePlatform.Value
        return cls.CURRENT if "current" == value else cls.for_value(value)


SciePlatform.seal()


class Provider(Enum["Provider.Value"]):
    class Value(Enum.Value):
        pass

    PythonBuildStandalone = Value("PythonBuildStandalone")
    PyPy = Value("PyPy")


Provider.seal()


@attr.s(frozen=True)
class InterpreterDistribution(object):
    provider = attr.ib()  # type: Provider.Value
    platform = attr.ib()  # type: SciePlatform.Value
    version = attr.ib()  # type: Union[Tuple[int, int], Tuple[int, int, int]]
    release = attr.ib(default=None)  # type: Optional[str]

    @property
    def version_str(self):
        # type: () -> str

        # N.B.: PyPy distribution archives only advertise a major and minor version.
        return ".".join(
            map(str, self.version[:2] if Provider.PyPy is self.provider else self.version)
        )

    def render_description(self):
        # type: () -> str
        return "{python_type} {version} on {platform}".format(
            python_type="PyPy" if Provider.PyPy is self.provider else "CPython",
            version=self.version_str,
            platform=self.platform,
        )


@attr.s(frozen=True)
class ScieInfo(object):
    style = attr.ib()  # type: ScieStyle.Value
    interpreter = attr.ib()  # type: InterpreterDistribution
    file = attr.ib()  # type: str

    @property
    def platform(self):
        # type: () -> SciePlatform.Value
        return self.interpreter.platform

    @property
    def python_version(self):
        # type: () -> Union[Tuple[int, int], Tuple[int, int, int]]
        return self.interpreter.version


class Url(str):
    pass


class File(str):
    pass


@attr.s(frozen=True)
class ScieOptions(object):
    style = attr.ib(default=ScieStyle.LAZY)  # type: ScieStyle.Value
    naming_style = attr.ib(default=None)  # type: Optional[PlatformNamingStyle.Value]
    scie_only = attr.ib(default=False)  # type: bool
    busybox_entrypoints = attr.ib(default=None)  # type: Optional[BusyBoxEntryPoints]
    busybox_pex_entrypoint_env_passthrough = attr.ib(default=False)  # type: bool
    platforms = attr.ib(default=())  # type: Tuple[SciePlatform.Value, ...]
    pbs_release = attr.ib(default=None)  # type: Optional[str]
    pypy_release = attr.ib(default=None)  # type: Optional[str]
    python_version = attr.ib(
        default=None
    )  # type: Optional[Union[Tuple[int, int], Tuple[int, int, int]]]
    pbs_stripped = attr.ib(default=False)  # type: bool
    hash_algorithms = attr.ib(default=())  # type: Tuple[str, ...]
    science_binary = attr.ib(default=None)  # type: Optional[Union[File, Url]]

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
        return cls._from_platform_specs(
            options=options,
            platform_specs=tuple(PlatformSpec.from_tag(tag) for tag in tags),
        )

    @classmethod
    def from_targets(
        cls,
        options,  # type: ScieOptions
        targets,  # type: Targets
    ):
        # type: (...) -> ScieConfiguration
        return cls._from_platform_specs(
            options=options,
            platform_specs=tuple(target.platform for target in targets.unique_targets()),
        )

    @classmethod
    def _from_platform_specs(
        cls,
        options,  # type: ScieOptions
        platform_specs,  # type: Iterable[PlatformSpec]
    ):
        # type: (...) -> ScieConfiguration

        python_version = options.python_version
        python_versions_by_platform = defaultdict(
            set
        )  # type: DefaultDict[SciePlatform.Value, Set[Union[Tuple[int, int], Tuple[int, int, int]]]]
        for platform_spec in platform_specs:
            if python_version:
                plat_python_version = python_version
            elif len(platform_spec.version_info) < 2:
                continue
            else:
                # Here were guessing an available PBS CPython version. Since a triple is unlikely to
                # hit, we just use major / minor. If the user wants control they can specify
                # options.python_version via `--scie-python-version`.
                plat_python_version = cast(
                    "Union[Tuple[int, int], Tuple[int, int, int]]",
                    platform_spec.version_info,
                )[:2]

            platform_str = platform_spec.platform
            is_aarch64 = "arm64" in platform_str or "aarch64" in platform_str
            is_armv7l = "armv7l" in platform_str or "armv8l" in platform_str
            is_ppc64le = "ppc64le" in platform_str
            is_s390x = "s390x" in platform_str
            is_x86_64 = "amd64" in platform_str or "x86_64" in platform_str
            if not is_aarch64 ^ is_armv7l ^ is_ppc64le ^ is_s390x ^ is_x86_64:
                continue

            if "linux" in platform_str:
                if is_aarch64:
                    scie_platform = SciePlatform.LINUX_AARCH64
                elif is_armv7l:
                    scie_platform = SciePlatform.LINUX_ARMV7L
                elif is_ppc64le:
                    scie_platform = SciePlatform.LINUX_PPC64LE
                elif is_s390x:
                    scie_platform = SciePlatform.LINUX_S390X
                else:
                    scie_platform = SciePlatform.LINUX_X86_64
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

            if platform_spec.impl in ("py", "cp"):
                # Python Build Standalone does not support CPython<3.8.
                if plat_python_version < (3, 8):
                    continue
                provider = Provider.PythonBuildStandalone
            elif "pp" == platform_spec.impl:
                # PyPy distributions for Linux aarch64 start with 3.7 (and PyPy always releases for
                # 2.7).
                if (
                    SciePlatform.LINUX_AARCH64 is scie_platform
                    and plat_python_version[0] == 3
                    and plat_python_version < (3, 7)
                ):
                    continue
                # PyPy distributions are not available for Linux armv7l
                if SciePlatform.LINUX_ARMV7L is scie_platform:
                    continue
                # PyPy distributions for Linux ppc64le are only available for 2.7 and 3.{5,6}.
                if (
                    SciePlatform.LINUX_PPC64LE is scie_platform
                    and plat_python_version[0] == 3
                    and plat_python_version >= (3, 7)
                ):
                    continue
                # PyPy distributions for Mac arm64 start with 3.8 (and PyPy always releases for
                # 2.7).
                if (
                    SciePlatform.MACOS_AARCH64 is scie_platform
                    and plat_python_version[0] == 3
                    and plat_python_version < (3, 8)
                ):
                    continue
                provider = Provider.PyPy
            else:
                # Pex only supports platform independent Python, CPython and PyPy.
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
            InterpreterDistribution(
                provider=provider,
                platform=scie_platform,
                release=(
                    options.pbs_release
                    if Provider.PythonBuildStandalone is provider
                    else options.pypy_release
                ),
                version=max(python_versions),
            )
            for scie_platform, python_versions in sorted(python_versions_by_platform.items())
        )
        return cls(options=options, interpreters=tuple(scie_targets))

    options = attr.ib()  # type: ScieOptions
    interpreters = attr.ib()  # type: Tuple[InterpreterDistribution, ...]

    def __len__(self):
        # type: () -> int
        return len(self.interpreters)
