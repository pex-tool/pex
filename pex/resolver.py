# coding=utf-8
# Copyright 2014 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import functools
import glob
import hashlib
import itertools
import os
import tarfile
import zipfile
from abc import abstractmethod
from collections import OrderedDict, defaultdict

from pex import targets
from pex.atomic_directory import AtomicDirectory, atomic_directory
from pex.cache.dirs import BuiltWheelDir, CacheDir
from pex.common import (
    open_zip,
    pluralize,
    safe_mkdir,
    safe_mkdtemp,
    safe_open,
    safe_relative_symlink,
)
from pex.compatibility import url_unquote, urlparse
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import (
    DistMetadata,
    Distribution,
    Requirement,
    is_tar_sdist,
    is_wheel,
    is_zip_sdist,
)
from pex.exceptions import production_assert
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.jobs import Raise, SpawnedJob, execute_parallel, iter_map_parallel
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pep_376 import InstalledWheel
from pex.pep_425 import CompatibilityTags
from pex.pep_427 import InstallableType, WheelError, install_wheel_chroot
from pex.pep_503 import ProjectName
from pex.pip.download_observer import DownloadObserver
from pex.pip.installation import get_pip
from pex.pip.tool import PackageIndexConfiguration
from pex.pip.version import PipVersionValue
from pex.requirements import LocalProjectRequirement, URLRequirement
from pex.resolve.package_repository import ReposConfiguration
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import BuildConfiguration, PipLog, ResolverVersion
from pex.resolve.resolvers import (
    ResolvedDistribution,
    Resolver,
    ResolveResult,
    Unsatisfiable,
    Untranslatable,
    check_resolve,
)
from pex.resolve.target_system import TargetSystem, UniversalTarget
from pex.targets import AbbreviatedPlatform, CompletePlatform, LocalInterpreter, Target, Targets
from pex.third_party.packaging.tags import Tag
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import (
        DefaultDict,
        Dict,
        FrozenSet,
        Iterable,
        Iterator,
        List,
        Mapping,
        Optional,
        Sequence,
        Set,
        Tuple,
        Union,
    )

    import attr  # vendor:skip

    from pex.requirements import ParsedRequirement
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class DownloadTarget(object):
    @classmethod
    def current(cls):
        # type: () -> DownloadTarget
        return cls(target=targets.current())

    target = attr.ib()  # type: Target
    universal_target = attr.ib(default=None)  # type: Optional[UniversalTarget]

    def render_description(self):
        # type: () -> str
        target_description = self.target.render_description()
        if self.universal_target:
            description_components = ["universal resolve"]
            if self.universal_target.systems and frozenset(
                self.universal_target.systems
            ) != frozenset(TargetSystem.values()):
                description_components.append(
                    "targeting {systems}".format(
                        systems=" and ".join(map(str, self.universal_target.systems))
                    )
                )
            if self.universal_target.implementation:
                description_components.append(
                    "for {impl}".format(impl=self.universal_target.implementation)
                )
            description_components.append("using {target}".format(target=target_description))
            return " ".join(description_components)
        return target_description

    def id(self, complete=False):
        # type: (bool) -> str

        if self.universal_target:
            id_components = ["universal"]
            if self.universal_target.implementation:
                id_components.append(str(self.universal_target.implementation))
            id_components.append(
                "-and-".join(map(str, self.universal_target.systems or TargetSystem.values()))
            )
            if complete:
                id_components.append(
                    hashlib.sha1(str(self.universal_target.marker()).encode("utf-8")).hexdigest()
                )
            return "-".join(id_components)

        if isinstance(self.target, LocalInterpreter):
            # e.g.: CPython 2.7.18
            return self.target.interpreter.version_string
        if isinstance(self.target, AbbreviatedPlatform):
            return str(self.target.platform)
        if isinstance(self.target, CompletePlatform):
            return str(self.target.platform.tag)

        return self.target.id


def _uniqued_targets(targets=None):
    # type: (Optional[Iterable[DownloadTarget]]) -> Tuple[DownloadTarget, ...]
    return tuple(OrderedSet(targets)) if targets is not None else ()


@attr.s(frozen=True)
class PipLogManager(object):
    @staticmethod
    def _target_id(download_target):
        # type: (DownloadTarget) -> str

        universal_target = download_target.universal_target
        if universal_target:
            id_components = ["universal"]
            if universal_target.implementation:
                id_components.append(str(universal_target.implementation))
            id_components.extend(map(str, universal_target.systems or TargetSystem.values()))
            return "-and-".join(id_components)

        target = download_target.target
        if isinstance(target, LocalInterpreter):
            # e.g.: CPython 2.7.18
            return target.interpreter.version_string
        if isinstance(target, AbbreviatedPlatform):
            return str(target.platform)
        if isinstance(target, CompletePlatform):
            return str(target.platform.tag)
        return target.id

    @classmethod
    def create(
        cls,
        log,  # type: Optional[PipLog]
        download_targets,  # type: Sequence[DownloadTarget]
    ):
        # type: (...) -> PipLogManager
        log_by_download_target = {}  # type: Dict[DownloadTarget, str]
        if log and len(download_targets) == 1:
            log_by_download_target[download_targets[0]] = log.path
        elif log:
            log_dir = safe_mkdtemp(prefix="pex-pip-log.")
            log_by_download_target.update(
                (
                    download_target,
                    os.path.join(
                        log_dir,
                        "pip.{target}.log".format(target=download_target.id(complete=True)),
                    ),
                )
                for download_target in download_targets
            )
        return cls(log=log, log_by_download_target=log_by_download_target)

    log = attr.ib()  # type: Optional[PipLog]
    _log_by_download_target = attr.ib()  # type: Mapping[DownloadTarget, str]

    def finalize_log(self):
        # type: () -> None
        if not self.log:
            return

        target_count = len(self._log_by_download_target)
        if target_count <= 1:
            return

        with safe_open(self.log.path, "a") as out_fp:
            for index, (download_target, log) in enumerate(
                self._log_by_download_target.items(), start=1
            ):
                prefix = "{index}/{count}]{target}".format(
                    index=index, count=target_count, target=download_target.id()
                )
                if not os.path.exists(log):
                    print(
                        "{prefix}: WARNING: no Pip log was generated!".format(prefix=prefix),
                        file=out_fp,
                    )
                    continue

                with open(log) as in_fp:
                    for line in in_fp:
                        out_fp.write("{prefix}: {line}".format(prefix=prefix, line=line))

    def get_log(self, download_target):
        # type: (DownloadTarget) -> Optional[str]
        return self._log_by_download_target.get(download_target)


@attr.s(frozen=True)
class DownloadRequest(object):
    download_targets = attr.ib(converter=_uniqued_targets)  # type: Tuple[DownloadTarget, ...]
    direct_requirements = attr.ib()  # type: Iterable[ParsedRequirement]
    requirements = attr.ib(default=None)  # type: Optional[Iterable[str]]
    requirement_files = attr.ib(default=None)  # type: Optional[Iterable[str]]
    constraint_files = attr.ib(default=None)  # type: Optional[Iterable[str]]
    allow_prereleases = attr.ib(default=False)  # type: bool
    transitive = attr.ib(default=True)  # type: bool
    package_index_configuration = attr.ib(default=None)  # type: Optional[PackageIndexConfiguration]
    build_configuration = attr.ib(default=BuildConfiguration())  # type: BuildConfiguration
    observer = attr.ib(default=None)  # type: Optional[ResolveObserver]
    pip_log = attr.ib(default=None)  # type: Optional[PipLog]
    pip_version = attr.ib(default=None)  # type: Optional[PipVersionValue]
    resolver = attr.ib(default=None)  # type: Optional[Resolver]
    dependency_configuration = attr.ib(
        default=DependencyConfiguration()
    )  # type: DependencyConfiguration

    def iter_local_projects(self):
        # type: () -> Iterator[BuildRequest]
        for requirement in self.direct_requirements:
            if isinstance(requirement, LocalProjectRequirement):
                for download_target in self.download_targets:
                    yield BuildRequest.create(
                        target=download_target.target, source_path=requirement.path
                    )

    def download_distributions(self, dest=None, max_parallel_jobs=None):
        # type: (...) -> List[DownloadResult]
        if not self.requirements and not self.requirement_files:
            # Nothing to resolve.
            return []

        dest = dest or safe_mkdtemp(
            prefix="resolver_download.", dir=safe_mkdir(CacheDir.DOWNLOADS.path(".tmp"))
        )

        log_manager = PipLogManager.create(self.pip_log, self.download_targets)
        if self.pip_log and not self.pip_log.user_specified:
            TRACER.log(
                "Preserving `pip download` log at {log_path}".format(log_path=self.pip_log.path),
                V=ENV.PEX_VERBOSE,
            )

        requirement_config = RequirementConfiguration(
            requirements=self.requirements,
            requirement_files=self.requirement_files,
            constraint_files=self.constraint_files,
        )
        network_configuration = (
            self.package_index_configuration.network_configuration
            if self.package_index_configuration
            else None
        )
        subdirectory_by_filename = {}  # type: Dict[str, str]
        for parsed_requirement in requirement_config.parse_requirements(network_configuration):
            if not isinstance(parsed_requirement, URLRequirement):
                continue
            subdirectory = parsed_requirement.subdirectory
            if subdirectory:
                subdirectory_by_filename[parsed_requirement.filename] = subdirectory

        spawn_download = functools.partial(
            self._spawn_download,
            resolved_dists_dir=dest,
            log_manager=log_manager,
            subdirectory_by_filename=subdirectory_by_filename,
        )
        with TRACER.timed(
            "Resolving for:\n  {}".format(
                "\n  ".join(target.render_description() for target in self.download_targets)
            )
        ):
            try:
                return list(
                    execute_parallel(
                        inputs=self.download_targets,
                        spawn_func=spawn_download,
                        error_handler=Raise[DownloadTarget, DownloadResult](Unsatisfiable),
                        max_jobs=max_parallel_jobs,
                    )
                )
            finally:
                log_manager.finalize_log()

    def _spawn_download(
        self,
        download_target,  # type: DownloadTarget
        resolved_dists_dir,  # type: str
        log_manager,  # type: PipLogManager
        subdirectory_by_filename,  # type: Mapping[str, str]
    ):
        # type: (...) -> SpawnedJob[DownloadResult]

        download_dir = os.path.join(resolved_dists_dir, download_target.id(complete=True))
        observer = (
            self.observer.observe_download(
                download_target=download_target, download_dir=download_dir
            )
            if self.observer
            else None
        )

        download_result = DownloadResult(download_target, download_dir, subdirectory_by_filename)
        target = download_target.target
        download_job = get_pip(
            interpreter=target.get_interpreter(),
            version=self.pip_version,
            resolver=self.resolver,
            extra_requirements=(
                self.package_index_configuration.extra_pip_requirements
                if self.package_index_configuration
                else ()
            ),
        ).spawn_download_distributions(
            download_dir=download_dir,
            requirements=self.requirements,
            requirement_files=self.requirement_files,
            constraint_files=self.constraint_files,
            allow_prereleases=self.allow_prereleases,
            transitive=self.transitive,
            target=target,
            package_index_configuration=self.package_index_configuration,
            build_configuration=self.build_configuration,
            observer=observer,
            dependency_configuration=self.dependency_configuration,
            universal_target=download_target.universal_target,
            log=log_manager.get_log(download_target),
        )

        return SpawnedJob.wait(job=download_job, result=download_result)


@attr.s(frozen=True)
class DownloadResult(object):
    @staticmethod
    def _is_wheel(path):
        # type: (str) -> bool
        return is_wheel(path) and zipfile.is_zipfile(path)

    download_target = attr.ib()  # type: DownloadTarget
    download_dir = attr.ib()  # type: str
    subdirectory_by_filename = attr.ib()  # type: Mapping[str, str]

    def _iter_distribution_paths(self):
        # type: () -> Iterator[str]
        if not os.path.exists(self.download_dir):
            return
        for distribution in os.listdir(self.download_dir):
            yield os.path.join(self.download_dir, distribution)

    def build_requests(self):
        # type: () -> Iterator[BuildRequest]
        for distribution_path in self._iter_distribution_paths():
            if not self._is_wheel(distribution_path):
                subdirectory = self.subdirectory_by_filename.get(
                    os.path.basename(distribution_path)
                )
                yield BuildRequest.create(
                    target=self.download_target,
                    source_path=distribution_path,
                    subdirectory=subdirectory,
                )

    def install_requests(self):
        # type: () -> Iterator[InstallRequest]
        for distribution_path in self._iter_distribution_paths():
            if self._is_wheel(distribution_path):
                yield InstallRequest.create(
                    target=self.download_target, wheel_path=distribution_path
                )


class IntegrityError(Exception):
    pass


def fingerprint_path(path):
    # type: (str) -> str

    # We switched from sha1 to sha256 at the transition from using `pip install --target` to
    # `pip install --prefix` to serve two purposes:
    # 1. Insulate the new installation scheme from the old.
    # 2. Move past sha1 which was shown to have practical collision attacks in 2019.
    #
    # The installation scheme switch was the primary purpose and switching hashes proved a pragmatic
    # insulation. If the `pip install --prefix` re-arrangement scheme evolves, then some other
    # option than switching hashing algorithms will be needed, like post-fixing a running version
    # integer or just mixing one into the hashed content.
    #
    # See: https://github.com/pex-tool/pex/issues/1655 for a general overview of these cache
    # structure concerns.
    hasher = hashlib.sha256

    if os.path.isdir(path):
        return CacheHelper.dir_hash(path, hasher=hasher)
    return CacheHelper.hash(path, hasher=hasher)


class BuildError(Exception):
    pass


def _as_download_target(target):
    # type: (Union[DownloadTarget, Target]) -> DownloadTarget
    return target if isinstance(target, DownloadTarget) else DownloadTarget(target)


@attr.s(frozen=True)
class BuildRequest(object):
    @classmethod
    def create(
        cls,
        target,  # type: Union[DownloadTarget, Target]
        source_path,  # type: str
        subdirectory=None,  # type: Optional[str]
    ):
        # type: (...) -> BuildRequest
        fingerprint = fingerprint_path(source_path)
        return cls(
            download_target=_as_download_target(target),
            source_path=source_path,
            fingerprint=fingerprint,
            subdirectory=subdirectory,
        )

    download_target = attr.ib(converter=_as_download_target)  # type: DownloadTarget
    source_path = attr.ib()  # type: str
    fingerprint = attr.ib()  # type: str
    subdirectory = attr.ib()  # type: Optional[str]

    @property
    def target(self):
        # type: () -> Target
        return self.download_target.target

    def prepare(self):
        # type: () -> str

        if os.path.isdir(self.source_path):
            if self.subdirectory:
                return os.path.join(self.source_path, self.subdirectory)
            return self.source_path

        extract_dir = os.path.join(safe_mkdtemp(), "project")
        if is_zip_sdist(self.source_path):
            with open_zip(self.source_path) as zf:
                zf.extractall(extract_dir)
        elif is_tar_sdist(self.source_path):
            with tarfile.open(self.source_path) as tf:
                tf.extractall(extract_dir)
        else:
            raise BuildError(
                "Unexpected archive type for sdist {project}".format(project=self.source_path)
            )

        listing = os.listdir(extract_dir)
        if len(listing) != 1:
            raise BuildError(
                "Expected one top-level project directory to be extracted from {project}, "
                "found {count}: {listing}".format(
                    project=self.source_path, count=len(listing), listing=", ".join(listing)
                )
            )
        project_directory = os.path.join(extract_dir, listing[0])
        if self.subdirectory:
            project_directory = os.path.join(project_directory, self.subdirectory)
        return project_directory

    def result(self, source_path=None):
        # type: (Optional[str]) -> BuildResult
        return BuildResult.from_request(self, source_path=source_path)


@attr.s(frozen=True)
class BuildResult(object):
    @classmethod
    def from_request(
        cls,
        build_request,  # type: BuildRequest
        source_path=None,  # type: Optional[str]
    ):
        # type: (...) -> BuildResult
        built_wheel = BuiltWheelDir.create(
            sdist=source_path or build_request.source_path,
            fingerprint=build_request.fingerprint,
            target=build_request.target,
        )
        return cls(request=build_request, atomic_dir=AtomicDirectory(built_wheel.dist_dir))

    request = attr.ib()  # type: BuildRequest
    _atomic_dir = attr.ib()  # type: AtomicDirectory

    @property
    def is_built(self):
        # type: () -> bool
        return self._atomic_dir.is_finalized()

    @property
    def build_dir(self):
        # type: () -> str
        return self._atomic_dir.work_dir

    @property
    def dist_dir(self):
        # type: () -> str
        return self._atomic_dir.target_dir

    def finalize_build(self, check_compatible=True):
        # type: (bool) -> InstallRequest
        self._atomic_dir.finalize()
        wheels = glob.glob(os.path.join(self.dist_dir, "*.whl"))
        if len(wheels) != 1:
            raise AssertionError(
                "Build of {request} produced {count} artifacts; expected 1:\n{actual}".format(
                    request=self.request,
                    count=len(wheels),
                    actual="\n".join(
                        "{index}. {wheel}".format(index=index, wheel=wheel)
                        for index, wheel in enumerate(wheels)
                    ),
                )
            )
        wheel_path = wheels[0]
        if check_compatible and self.request.target.is_foreign:
            wheel = Distribution.load(wheel_path)
            wheel_tag_match = self.request.target.wheel_applies(wheel)
            incompatible = isinstance(self.request.target, CompletePlatform) and not wheel_tag_match
            if (
                not incompatible
                and not wheel_tag_match
                and isinstance(self.request.target, AbbreviatedPlatform)
            ):

                def collect_platforms(tags):
                    # type: (Iterable[Tag]) -> Tuple[FrozenSet[str], bool]
                    platforms = []  # type: List[str]
                    is_linux = False
                    for tag in tags:
                        platforms.append(tag.platform)
                        if "linux" in tag.platform:
                            is_linux = True
                    return frozenset(platforms), is_linux

                wheel_platform_tags, is_linux_wheel = collect_platforms(
                    CompatibilityTags.from_wheel(wheel)
                )
                abbreviated_target_platform_tags, is_linux_abbreviated_target = collect_platforms(
                    self.request.target.supported_tags
                )
                # N.B.: We can't say much about whether an abbreviated platform will match in the
                # end unless the platform is a mismatch (i.e. linux vs mac). We check only for that
                # sort of mismatch here. Further, we don't wade into manylinux compatibility and
                # just consider a locally built linux wheel may match a linux target.
                if not (is_linux_wheel and is_linux_abbreviated_target):
                    if is_linux_wheel ^ is_linux_abbreviated_target:
                        incompatible = True
                    else:
                        common_platforms = abbreviated_target_platform_tags.intersection(
                            wheel_platform_tags
                        )
                        if not common_platforms:
                            incompatible = True
                        elif common_platforms == frozenset(["any"]):
                            # N.B.: In the "any" platform case, we know we have complete information
                            # about the foreign abbreviated target platform (the `pip debug` command
                            # we run to learn compatible tags has enough information to give us all
                            # the "any" tags accurately); so we can expect an exact wheel tag match.
                            incompatible = not wheel_tag_match
            if incompatible:
                raise ValueError(
                    "No pre-built wheel was available for {project_name} {version}.\n"
                    "Successfully built the wheel {wheel} from the sdist {sdist} but it is not "
                    "compatible with the requested foreign target {target}.\n"
                    "You'll need to build a wheel from {sdist} on the foreign target platform and "
                    "make it available to Pex via a `--find-links` repo or a custom "
                    "`--index`.".format(
                        project_name=wheel.project_name,
                        version=wheel.version,
                        wheel=os.path.basename(wheel_path),
                        sdist=os.path.basename(self.request.source_path),
                        target=self.request.target.render_description(),
                    )
                )
        return InstallRequest.create(self.request.target, wheel_path)


@attr.s(frozen=True)
class InstallRequest(object):
    @classmethod
    def create(
        cls,
        target,  # type: Union[DownloadTarget, Target]
        wheel_path,  # type: str
    ):
        # type: (...) -> InstallRequest
        fingerprint = fingerprint_path(wheel_path)
        return cls(
            download_target=_as_download_target(target),
            wheel_path=wheel_path,
            fingerprint=fingerprint,
        )

    download_target = attr.ib(converter=_as_download_target)  # type: DownloadTarget
    wheel_path = attr.ib()  # type: str
    fingerprint = attr.ib()  # type: str

    @property
    def target(self):
        # type: () -> Target
        return self.download_target.target

    @property
    def wheel_file(self):
        # type: () -> str
        return os.path.basename(self.wheel_path)

    def result(self, installation_root):
        # type: (str) -> InstallResult
        return InstallResult.from_request(self, installation_root=installation_root)


@attr.s(frozen=True)
class InstallResult(object):
    @classmethod
    def from_request(
        cls,
        install_request,  # type: InstallRequest
        installation_root,  # type: str
    ):
        # type: (...) -> InstallResult
        install_chroot = os.path.join(
            installation_root, install_request.fingerprint, install_request.wheel_file
        )
        return cls(
            request=install_request,
            installation_root=installation_root,
            atomic_dir=AtomicDirectory(install_chroot),
        )

    request = attr.ib()  # type: InstallRequest
    _installation_root = attr.ib()  # type: str
    _atomic_dir = attr.ib()  # type: AtomicDirectory

    @property
    def is_installed(self):
        # type: () -> bool
        return self._atomic_dir.is_finalized()

    def wheel_file(self):
        # type: () -> str
        return self.request.wheel_file

    @property
    def build_chroot(self):
        # type: () -> str
        return self._atomic_dir.work_dir

    @property
    def install_chroot(self):
        # type: () -> str
        return self._atomic_dir.target_dir

    def finalize_install(self, install_requests):
        # type: (Iterable[InstallRequest]) -> Iterator[ResolvedDistribution]
        self._atomic_dir.finalize()

        # The install_chroot is keyed by the hash of the wheel file (zip) we installed. Here we add
        # a key by the hash of the exploded wheel dir (the install_chroot). This latter key is used
        # by zipped PEXes at runtime to explode their wheel chroots to the filesystem. By adding
        # the key here we short-circuit the explode process for PEXes created and run on the same
        # machine.
        #
        # From a clean cache after building a simple pex this looks like:
        # $ rm -rf ~/.cache/pex
        # $ python -mpex -c pex -o /tmp/pex.pex .
        # $ tree -L 4 ~/.cache/pex/
        # /home/jsirois/.cache/pex/
        # ├── built_wheels
        # │ └── 1003685de2c3604dc6daab9540a66201c1d1f718
        # │     └── cp-38-cp38
        # │         └── pex-2.0.2-py2.py3-none-any.whl
        # └── installed_wheels
        #     ├── 2a594cef34d2e9109bad847358d57ac4615f81f4
        #     │ └── pex-2.0.2-py2.py3-none-any.whl
        #     │     ├── bin
        #     │     ├── pex
        #     │     └── pex-2.0.2.dist-info
        #     └── ae13cba3a8e50262f4d730699a11a5b79536e3e1
        #         └── pex-2.0.2-py2.py3-none-any.whl -> /home/jsirois/.cache/pex/installed_wheels/2a594cef34d2e9109bad847358d57ac4615f81f4/pex-2.0.2-py2.py3-none-any.whl  # noqa
        #
        # 11 directories, 1 file
        #
        # And we see in the created pex, the runtime key that the layout above satisfies:
        # $ unzip -qc /tmp/pex.pex PEX-INFO | jq .distributions
        # {
        #   "pex-2.0.2-py2.py3-none-any.whl": "ae13cba3a8e50262f4d730699a11a5b79536e3e1"
        # }
        #
        # When the pex is run, the runtime key is followed to the build time key, avoiding
        # re-unpacking the wheel:
        # $ PEX_VERBOSE=1 /tmp/pex.pex --version
        # pex: Found site-library: /usr/lib/python3.8/site-packages
        # pex: Tainted path element: /usr/lib/python3.8/site-packages
        # pex: Scrubbing from user site: /home/jsirois/.local/lib/python3.8/site-packages
        # pex: Scrubbing from site-packages: /usr/lib/python3.8/site-packages
        # pex: Activating PEX virtual environment from /tmp/pex.pex: 9.1ms
        # pex: Bootstrap complete, performing final sys.path modifications...
        # pex: PYTHONPATH contains:
        # pex:     /tmp/pex.pex
        # pex:   * /usr/lib/python38.zip
        # pex:     /usr/lib/python3.8
        # pex:     /usr/lib/python3.8/lib-dynload
        # pex:     /home/jsirois/.cache/pex/installed_wheels/2a594cef34d2e9109bad847358d57ac4615f81f4/pex-2.0.2-py2.py3-none-any.whl  # noqa
        # pex:   * /tmp/pex.pex/.bootstrap
        # pex:   * - paths that do not exist or will be imported via zipimport
        # pex.pex 2.0.2
        #
        cached_fingerprint = None  # type: Optional[str]
        try:
            installed_wheel = InstalledWheel.load(self.install_chroot)
        except InstalledWheel.LoadError:
            # We support legacy chroots below by calculating the chroot fingerprint just in time.
            pass
        else:
            cached_fingerprint = installed_wheel.fingerprint

        wheel_dir_hash = cached_fingerprint or fingerprint_path(self.install_chroot)
        runtime_key_dir = os.path.join(self._installation_root, wheel_dir_hash)
        with atomic_directory(runtime_key_dir) as atomic_dir:
            if not atomic_dir.is_finalized():
                # Note: Create a relative path symlink between the two directories so that the
                # PEX_ROOT can be used within a chroot environment where the prefix of the path may
                # change between programs running inside and outside of the chroot.
                safe_relative_symlink(
                    self.install_chroot, os.path.join(atomic_dir.work_dir, self.request.wheel_file)
                )

        return self._iter_resolved_distributions(install_requests, fingerprint=wheel_dir_hash)

    def _iter_resolved_distributions(
        self,
        install_requests,  # type: Iterable[InstallRequest]
        fingerprint,  # type: str
    ):
        # type: (...) -> Iterator[ResolvedDistribution]
        if self.is_installed:
            distribution = Distribution.load(self.install_chroot)
            for install_request in install_requests:
                yield ResolvedDistribution(
                    target=install_request.target,
                    fingerprinted_distribution=FingerprintedDistribution(distribution, fingerprint),
                )


class WheelBuilder(object):
    def __init__(
        self,
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
        build_configuration=BuildConfiguration(),  # type: BuildConfiguration
        verify_wheels=True,  # type: bool
        pip_version=None,  # type: Optional[PipVersionValue]
        resolver=None,  # type: Optional[Resolver]
    ):
        # type: (...) -> None
        self._package_index_configuration = package_index_configuration
        self._build_configuration = build_configuration
        self._verify_wheels = verify_wheels
        self._pip_version = pip_version
        self._resolver = resolver

    @staticmethod
    def _categorize_build_requests(
        build_requests,  # type: Iterable[BuildRequest]
        check_compatible=True,  # type: bool
    ):
        # type: (...) -> Tuple[Iterable[BuildRequest], DefaultDict[str, OrderedSet[InstallRequest]]]
        unsatisfied_build_requests = []
        build_results = defaultdict(
            OrderedSet
        )  # type: DefaultDict[str, OrderedSet[InstallRequest]]
        for build_request in build_requests:
            build_result = build_request.result()
            if not build_result.is_built:
                TRACER.log(
                    "Building {} to {}".format(build_request.source_path, build_result.dist_dir)
                )
                unsatisfied_build_requests.append(build_request)
            else:
                TRACER.log(
                    "Using cached build of {} at {}".format(
                        build_request.source_path, build_result.dist_dir
                    )
                )
                build_results[build_request.source_path].add(
                    build_result.finalize_build(check_compatible=check_compatible)
                )
        return unsatisfied_build_requests, build_results

    def _spawn_wheel_build(self, build_request):
        # type: (BuildRequest) -> SpawnedJob[BuildResult]
        source_path = build_request.prepare()
        build_result = build_request.result(source_path)
        build_job = get_pip(
            interpreter=build_request.target.get_interpreter(),
            version=self._pip_version,
            resolver=self._resolver,
            extra_requirements=(
                self._package_index_configuration.extra_pip_requirements
                if self._package_index_configuration is not None
                else ()
            ),
        ).spawn_build_wheels(
            distributions=[source_path],
            wheel_dir=build_result.build_dir,
            package_index_configuration=self._package_index_configuration,
            interpreter=build_request.target.get_interpreter(),
            build_configuration=self._build_configuration,
            verify=self._verify_wheels,
        )
        return SpawnedJob.wait(job=build_job, result=build_result)

    def build_wheels(
        self,
        build_requests,  # type: Iterable[BuildRequest]
        max_parallel_jobs=None,  # type: Optional[int]
        check_compatible=True,  # type: bool
    ):
        # type: (...) -> Mapping[str, OrderedSet[InstallRequest]]

        if not build_requests:
            # Nothing to build or install.
            return {}

        with TRACER.timed(
            "Building distributions for:" "\n  {}".format("\n  ".join(map(str, build_requests)))
        ):
            build_requests, build_results = self._categorize_build_requests(
                build_requests=build_requests,
                check_compatible=check_compatible,
            )

            for build_result in execute_parallel(
                inputs=build_requests,
                spawn_func=self._spawn_wheel_build,
                error_handler=Raise[BuildRequest, BuildResult](Untranslatable),
                max_jobs=max_parallel_jobs,
            ):
                build_results[build_result.request.source_path].add(
                    build_result.finalize_build(check_compatible=check_compatible)
                )

        return build_results


@attr.s(frozen=True)
class DirectRequirements(object):
    @classmethod
    def calculate(
        cls,
        direct_requirements,  # type: Iterable[ParsedRequirement]
        install_requests,  # type: Mapping[str, OrderedSet[InstallRequest]]
        local_project_directory_to_sdist=None,  # type: Optional[Mapping[str, str]]
    ):
        # type: (...) -> DirectRequirements

        # 3. All requirements are now in wheel form: calculate any missing direct requirement
        #    project names from the wheel names.
        with TRACER.timed(
            "Calculating project names for direct requirements:"
            "\n  {}".format("\n  ".join(map(str, direct_requirements)))
        ):

            def iter_direct_requirements():
                # type: () -> Iterator[Requirement]
                for requirement in direct_requirements:
                    if not isinstance(requirement, LocalProjectRequirement):
                        yield requirement.requirement
                        continue

                    if requirement.project_name is not None:
                        yield requirement.as_requirement()
                        continue

                    install_reqs = install_requests.get(requirement.path)
                    if not install_reqs and local_project_directory_to_sdist:
                        local_project_directory = local_project_directory_to_sdist.get(
                            requirement.path
                        )
                        if local_project_directory:
                            install_reqs = install_requests.get(local_project_directory)
                    if not install_reqs:
                        raise AssertionError(
                            "Failed to compute a project name for {requirement}. No corresponding "
                            "wheel was found from amongst:\n{install_requests}".format(
                                requirement=requirement,
                                install_requests="\n".join(
                                    sorted(
                                        "{path} -> {wheel_path} {fingerprint}".format(
                                            path=path,
                                            wheel_path=build_result.wheel_path,
                                            fingerprint=build_result.fingerprint,
                                        )
                                        for path, build_results in install_requests.items()
                                        for build_result in build_results
                                    )
                                ),
                            )
                        )
                    for install_req in install_reqs:
                        yield requirement.as_requirement(dist=install_req.wheel_path)

            direct_requirements_by_project_name = defaultdict(
                OrderedSet
            )  # type: DefaultDict[ProjectName, OrderedSet[Requirement]]
            for direct_requirement in iter_direct_requirements():
                direct_requirements_by_project_name[direct_requirement.project_name].add(
                    direct_requirement
                )
            return cls(direct_requirements_by_project_name)

    _direct_requirements_by_project_name = (
        attr.ib()
    )  # Mapping[ProjectName, OrderedSet[Requirement]]

    def adjust(self, distributions):
        # type: (Iterable[ResolvedDistribution]) -> Iterable[ResolvedDistribution]
        resolved_distributions = OrderedSet()  # type: OrderedSet[ResolvedDistribution]
        for resolved_distribution in distributions:
            distribution = resolved_distribution.distribution
            direct_reqs = [
                req
                for req in self._direct_requirements_by_project_name[
                    distribution.metadata.project_name
                ]
                if distribution in req and resolved_distribution.target.requirement_applies(req)
            ]
            resolved_distributions.add(
                resolved_distribution.with_direct_requirements(direct_requirements=direct_reqs)
            )
        return resolved_distributions


def _perform_install(
    installed_wheels_dir,  # type: str
    install_request,  # type: InstallRequest
):
    # type: (...) -> InstallResult
    install_result = install_request.result(installed_wheels_dir)
    install_wheel_chroot(wheel=install_request.wheel_path, destination=install_result.build_chroot)
    return install_result


class BuildAndInstallRequest(object):
    def __init__(
        self,
        build_requests,  # type: Iterable[BuildRequest]
        install_requests,  # type:  Iterable[InstallRequest]
        direct_requirements=None,  # type: Optional[Iterable[ParsedRequirement]]
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
        compile=False,  # type: bool
        build_configuration=BuildConfiguration(),  # type: BuildConfiguration
        verify_wheels=True,  # type: bool
        pip_version=None,  # type: Optional[PipVersionValue]
        resolver=None,  # type: Optional[Resolver]
        dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
    ):
        # type: (...) -> None
        self._build_requests = tuple(build_requests)
        self._install_requests = tuple(install_requests)
        self._direct_requirements = tuple(direct_requirements or ())
        self._compile = compile
        self._wheel_builder = WheelBuilder(
            package_index_configuration=package_index_configuration,
            build_configuration=build_configuration,
            verify_wheels=verify_wheels,
            pip_version=pip_version,
            resolver=resolver,
        )
        self._pip_version = pip_version
        self._resolver = resolver
        self._dependency_configuration = dependency_configuration

    @staticmethod
    def _categorize_install_requests(
        install_requests,  # type: Iterable[InstallRequest]
        installed_wheels_dir,  # type: str
    ):
        # type: (...) -> Tuple[Iterable[InstallRequest], Iterable[InstallResult]]
        unsatisfied_install_requests = []
        install_results = []
        for install_request in install_requests:
            install_result = install_request.result(installed_wheels_dir)
            if not install_result.is_installed:
                TRACER.log(
                    "Installing {} in {}".format(
                        install_request.wheel_path, install_result.install_chroot
                    ),
                    V=2,
                )
                unsatisfied_install_requests.append(install_request)
            else:
                TRACER.log(
                    "Using cached installation of {} at {}".format(
                        install_request.wheel_file, install_result.install_chroot
                    ),
                    V=2,
                )
                install_results.append(install_result)
        return unsatisfied_install_requests, install_results

    def _resolve_direct_file_deps(
        self,
        install_requests,  # type: Iterable[InstallRequest]
        max_parallel_jobs=None,  # type: Optional[int]
        analyzed=None,  # type: Optional[Set[ProjectName]]
    ):
        # type: (...) -> Iterable[InstallRequest]

        already_analyzed = analyzed or set()  # type: Set[ProjectName]

        to_install = OrderedSet()  # type: OrderedSet[InstallRequest]
        to_build = OrderedSet()  # type: OrderedSet[BuildRequest]
        for install_request in install_requests:
            metadata = DistMetadata.load(install_request.wheel_path)
            for requirement in metadata.requires_dists:
                if requirement.project_name in already_analyzed:
                    continue
                if not requirement.url:
                    continue
                urlinfo = urlparse.urlparse(requirement.url)
                if urlinfo.scheme != "file":
                    continue
                dist_path = url_unquote(urlinfo.path).rstrip()
                if not os.path.exists(dist_path):
                    raise Unsatisfiable(
                        "The {wheel} wheel has a dependency on {url} which does not exist on this "
                        "machine.".format(wheel=install_request.wheel_file, url=requirement.url)
                    )
                if is_wheel(dist_path):
                    to_install.add(InstallRequest.create(install_request.target, dist_path))
                else:
                    to_build.add(BuildRequest.create(install_request.target, dist_path))
            already_analyzed.add(metadata.project_name)

        all_install_requests = OrderedSet(install_requests)
        if to_build:
            build_results = self._wheel_builder.build_wheels(
                build_requests=to_build, max_parallel_jobs=max_parallel_jobs
            )
            to_install.update(itertools.chain.from_iterable(build_results.values()))
        if to_install:
            all_install_requests.update(
                self._resolve_direct_file_deps(
                    to_install, max_parallel_jobs=max_parallel_jobs, analyzed=already_analyzed
                )
            )
        return all_install_requests

    def _build_distributions(
        self,
        max_parallel_jobs=None,  # type: Optional[int]
        local_project_directory_to_sdist=None,  # type: Optional[Mapping[str, str]]
    ):
        # type: (...) -> Tuple[DirectRequirements, Iterable[InstallRequest]]

        to_install = list(self._install_requests)

        # 1. Build local projects and sdists.
        build_results = self._wheel_builder.build_wheels(
            build_requests=self._build_requests,
            max_parallel_jobs=max_parallel_jobs,
        )
        to_install.extend(itertools.chain.from_iterable(build_results.values()))

        # 2. (Recursively) post-process all wheels with file:// URL direct references. During the
        #    download phase, Pip considers these dependencies satisfied and does not download them
        #    or transfer them to the download directory (although it does download their
        #    non file:// URL dependencies); it just leaves them where they lay on the file system.
        all_install_requests = self._resolve_direct_file_deps(
            to_install, max_parallel_jobs=max_parallel_jobs
        )

        # 3. All requirements are now in wheel form: calculate any missing direct requirement
        #    project names from the wheel names.
        direct_requirements = DirectRequirements.calculate(
            self._direct_requirements,
            build_results,
            local_project_directory_to_sdist=local_project_directory_to_sdist,
        )

        return direct_requirements, all_install_requests

    def build_distributions(
        self,
        ignore_errors=False,  # type: bool
        max_parallel_jobs=None,  # type: Optional[int]
        local_project_directory_to_sdist=None,  # type: Optional[Mapping[str, str]]
    ):
        # type: (...) -> Iterable[ResolvedDistribution]

        if not any((self._build_requests, self._install_requests)):
            # Nothing to build or install.
            return ()

        direct_requirements, all_install_requests = self._build_distributions(
            max_parallel_jobs=max_parallel_jobs,
            local_project_directory_to_sdist=local_project_directory_to_sdist,
        )

        wheels = OrderedSet(
            ResolvedDistribution(
                target=install_request.target,
                fingerprinted_distribution=FingerprintedDistribution(
                    distribution=Distribution.load(install_request.wheel_path),
                    fingerprint=install_request.fingerprint,
                ),
            )
            for install_request in all_install_requests
        )  # type: OrderedSet[ResolvedDistribution]

        if not ignore_errors:
            with TRACER.timed("Checking build"):
                check_resolve(self._dependency_configuration, wheels)
        return direct_requirements.adjust(wheels)

    def install_distributions(
        self,
        ignore_errors=False,  # type: bool
        max_parallel_jobs=None,  # type: Optional[int]
        local_project_directory_to_sdist=None,  # type: Optional[Mapping[str, str]]
    ):
        # type: (...) -> Iterable[ResolvedDistribution]

        if not any((self._build_requests, self._install_requests)):
            # Nothing to build or install.
            return ()

        installed_wheels_dir = CacheDir.INSTALLED_WHEELS.path()
        perform_install = functools.partial(_perform_install, installed_wheels_dir)

        installations = []  # type: List[ResolvedDistribution]

        # 1. Gather all wheels to install, building sdists and local projects if needed.
        direct_requirements, all_install_requests = self._build_distributions(
            max_parallel_jobs=max_parallel_jobs,
            local_project_directory_to_sdist=local_project_directory_to_sdist,
        )

        # 2. Install wheels in individual chroots.

        # Dedup by wheel name; e.g.: only install universal wheels once even though they'll get
        # downloaded / built for each interpreter or platform.
        install_requests_by_wheel_file = (
            OrderedDict()
        )  # type: OrderedDict[str, List[InstallRequest]]
        for install_request in all_install_requests:
            install_requests_by_wheel_file.setdefault(install_request.wheel_file, []).append(
                install_request
            )

        representative_install_requests = [
            requests[0] for requests in install_requests_by_wheel_file.values()
        ]

        def add_installation(install_result):
            install_requests = install_requests_by_wheel_file[install_result.request.wheel_file]
            installations.extend(install_result.finalize_install(install_requests))

        with TRACER.timed(
            "Installing {} distributions".format(len(representative_install_requests))
        ):
            install_requests, install_results = self._categorize_install_requests(
                install_requests=representative_install_requests,
                installed_wheels_dir=installed_wheels_dir,
            )
            for install_result in install_results:
                add_installation(install_result)

            try:
                for install_result in iter_map_parallel(
                    inputs=install_requests,
                    function=perform_install,
                    noun="wheel",
                    verb="install",
                    verb_past="installed",
                    max_jobs=max_parallel_jobs,
                    costing_function=lambda req: os.path.getsize(req.wheel_path),
                    result_render_function=InstallResult.wheel_file,
                ):
                    add_installation(install_result)
            except WheelError as e:
                raise Untranslatable("Failed to install a wheel: {err}".format(err=e))

        installations = list(direct_requirements.adjust(installations))
        if not ignore_errors:
            with TRACER.timed("Checking install"):
                check_resolve(self._dependency_configuration, installations)
        return installations


def _parse_reqs(
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
):
    # type: (...) -> Iterable[ParsedRequirement]
    requirement_configuration = RequirementConfiguration(
        requirements=requirements, requirement_files=requirement_files
    )
    return requirement_configuration.parse_requirements(network_configuration=network_configuration)


def resolve(
    targets=Targets(),  # type: Targets
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    constraint_files=None,  # type: Optional[Iterable[str]]
    allow_prereleases=False,  # type: bool
    transitive=True,  # type: bool
    repos_configuration=ReposConfiguration(),  # type: ReposConfiguration
    resolver_version=None,  # type: Optional[ResolverVersion.Value]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    build_configuration=BuildConfiguration(),  # type: BuildConfiguration
    compile=False,  # type: bool
    max_parallel_jobs=None,  # type: Optional[int]
    ignore_errors=False,  # type: bool
    verify_wheels=True,  # type: bool
    pip_log=None,  # type: Optional[PipLog]
    pip_version=None,  # type: Optional[PipVersionValue]
    resolver=None,  # type: Optional[Resolver]
    use_pip_config=False,  # type: bool
    extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
    keyring_provider=None,  # type: Optional[str]
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> ResolveResult
    """Resolves all distributions needed to meet requirements for multiple distribution targets.

    The resulting distributions are installed in individual chroots that can be independently added
    to `sys.path`

    :keyword targets: The distribution target environments to resolve for.
    :keyword requirements: A sequence of requirement strings.
    :keyword requirement_files: A sequence of requirement file paths.
    :keyword constraint_files: A sequence of constraint file paths.
    :keyword allow_prereleases: Whether to include pre-release and development versions when
      resolving requirements. Defaults to ``False``, but any requirements that explicitly request
      pre-release or development versions will override this setting.
    :keyword transitive: Whether to resolve transitive dependencies of requirements.
      Defaults to ``True``.
    :keyword repos_configuration: Configuration for package repositories to resolve packages from.
    :keyword resolver_version: The resolver version to use.
    :keyword network_configuration: Configuration for network requests made downloading and building
      distributions.
    :keyword build_configuration: The configuration for building resolved projects.
    :keyword compile: Whether to pre-compile resolved distribution python sources.
      Defaults to ``False``.
    :keyword max_parallel_jobs: The maximum number of parallel jobs to use when resolving,
      building and installing distributions in a resolve. Defaults to the number of CPUs available.
    :keyword ignore_errors: Whether to ignore resolution solver errors. Defaults to ``False``.
    :keyword verify_wheels: Whether to verify wheels have valid metadata. Defaults to ``True``.
    :keyword pip_log: Preserve the `pip download` log and print its location to stderr.
      Defaults to ``False``.
    :returns: The installed distributions meeting all requirements and constraints.
    :raises Unsatisfiable: If ``requirements`` is not transitively satisfiable.
    :raises Untranslatable: If no compatible distributions could be acquired for
      a particular requirement.
    :raises ValueError: If a foreign platform was provided in `platforms`, and `use_wheel=False`.
    :raises ValueError: If `build=False` and `use_wheel=False`.
    """

    # A resolve happens in four stages broken into two phases:
    # 1. Download phase: resolves sdists and wheels in a single operation per distribution target.
    # 2. Install phase:
    #   1. Build local projects and sdists.
    #   2. Install wheels in individual chroots.
    #   3. Calculate the final resolved requirements.
    #
    # You'd think we might be able to just pip install all the requirements, but pexes can be
    # multi-platform / multi-interpreter, in which case only a subset of distributions resolved into
    # the PEX should be activated for the runtime interpreter. Sometimes there are platform specific
    # wheels and sometimes python version specific dists (backports being the common case). As such,
    # we need to be able to add each resolved distribution to the `sys.path` individually
    # (`PEXEnvironment` handles this selective activation at runtime). Since pip install only
    # accepts a single location to install all resolved dists, that won't work.
    #
    # This means we need to separately resolve all distributions, then install each in their own
    # chroot. To do this we use `pip download` for the resolve and download of all needed
    # distributions and then `pex.pep_427.install_wheel_chroot` to install each distribution in its
    # own chroot.
    #
    # As a complicating factor, the runtime activation scheme relies on PEP 425 tags; i.e.: wheel
    # names. Some requirements are only available or applicable in source form - either via sdist,
    # VCS URL or local projects. As such we need to insert a `pip wheel` step to generate wheels for
    # all requirements resolved in source form via `pip download` / inspection of requirements to
    # discover those that are local directories (local setup.py or pyproject.toml python projects).
    #
    # Finally, we must calculate the pinned requirement corresponding to each distribution we
    # resolved along with any environment markers that control which runtime environments the
    # requirement should be activated in.

    direct_requirements = _parse_reqs(requirements, requirement_files, network_configuration)
    package_index_configuration = PackageIndexConfiguration.create(
        pip_version=pip_version,
        resolver_version=resolver_version,
        repos_configuration=repos_configuration,
        network_configuration=network_configuration,
        use_pip_config=use_pip_config,
        extra_pip_requirements=extra_pip_requirements,
        keyring_provider=keyring_provider,
    )

    if not build_configuration.allow_wheels:
        foreign_targets = [
            target
            for target in targets.unique_targets()
            if not isinstance(target, LocalInterpreter)
        ]
        if foreign_targets:
            raise ValueError(
                "Cannot ignore wheels (use_wheel=False) when resolving for foreign {platforms}: "
                "{foreign_platforms}".format(
                    platforms=pluralize(foreign_targets, "platform"),
                    foreign_platforms=", ".join(
                        target.render_description() for target in foreign_targets
                    ),
                )
            )

    build_requests, download_results = _download_internal(
        targets=targets,
        direct_requirements=direct_requirements,
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
        allow_prereleases=allow_prereleases,
        transitive=transitive,
        package_index_configuration=package_index_configuration,
        build_configuration=build_configuration,
        max_parallel_jobs=max_parallel_jobs,
        pip_log=pip_log,
        pip_version=pip_version,
        resolver=resolver,
        dependency_configuration=dependency_configuration,
    )

    install_requests = []  # type: List[InstallRequest]
    for download_result in download_results:
        build_requests.extend(download_result.build_requests())
        install_requests.extend(download_result.install_requests())

    build_and_install_request = BuildAndInstallRequest(
        build_requests=build_requests,
        install_requests=install_requests,
        direct_requirements=direct_requirements,
        package_index_configuration=package_index_configuration,
        compile=compile,
        build_configuration=build_configuration,
        verify_wheels=verify_wheels,
        pip_version=pip_version,
        resolver=resolver,
        dependency_configuration=dependency_configuration,
    )

    ignore_errors = ignore_errors or not transitive
    distributions = tuple(
        build_and_install_request.install_distributions(
            ignore_errors=ignore_errors, max_parallel_jobs=max_parallel_jobs
        )
        if result_type is InstallableType.INSTALLED_WHEEL_CHROOT
        else build_and_install_request.build_distributions(
            ignore_errors=ignore_errors, max_parallel_jobs=max_parallel_jobs
        )
    )
    return ResolveResult(
        dependency_configuration=dependency_configuration,
        distributions=distributions,
        type=result_type,
    )


def _download_internal(
    targets,  # type: Targets
    direct_requirements,  # type: Iterable[ParsedRequirement]
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    constraint_files=None,  # type: Optional[Iterable[str]]
    allow_prereleases=False,  # type: bool
    transitive=True,  # type: bool
    package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
    build_configuration=BuildConfiguration(),  # type: BuildConfiguration
    dest=None,  # type: Optional[str]
    max_parallel_jobs=None,  # type: Optional[int]
    observer=None,  # type: Optional[ResolveObserver]
    pip_log=None,  # type: Optional[PipLog]
    pip_version=None,  # type: Optional[PipVersionValue]
    resolver=None,  # type: Optional[Resolver]
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
    universal_targets=(),  # type: Iterable[UniversalTarget]
):
    # type: (...) -> Tuple[List[BuildRequest], List[DownloadResult]]

    unique_targets = targets.unique_targets()
    if universal_targets:
        production_assert(len(unique_targets) == 1)
        target = unique_targets.pop()
        download_targets = tuple(
            DownloadTarget(target, universal_target=universal_target)
            for universal_target in universal_targets
        )
    else:
        download_targets = tuple(DownloadTarget(target) for target in unique_targets)

    download_request = DownloadRequest(
        download_targets=download_targets,
        direct_requirements=direct_requirements,
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
        allow_prereleases=allow_prereleases,
        transitive=transitive,
        package_index_configuration=package_index_configuration,
        build_configuration=build_configuration,
        observer=observer,
        pip_log=pip_log,
        pip_version=pip_version,
        resolver=resolver,
        dependency_configuration=dependency_configuration,
    )

    local_projects = list(download_request.iter_local_projects())
    download_results = download_request.download_distributions(
        dest=dest, max_parallel_jobs=max_parallel_jobs
    )
    return local_projects, download_results


@attr.s(frozen=True)
class LocalDistribution(object):
    path = attr.ib()  # type: str
    fingerprint = attr.ib()  # type: str
    download_target = attr.ib(factory=DownloadTarget.current)  # type: DownloadTarget
    subdirectory = attr.ib(default=None)  # type: Optional[str]

    @property
    def target(self):
        # type: () -> Target
        return self.download_target.target

    @fingerprint.default
    def _calculate_fingerprint(self):
        return fingerprint_path(self.path)

    @property
    def is_wheel(self):
        return is_wheel(self.path) and zipfile.is_zipfile(self.path)


@attr.s(frozen=True)
class Downloaded(object):
    local_distributions = attr.ib()  # type: Tuple[LocalDistribution, ...]


class ResolveObserver(object):
    @abstractmethod
    def observe_download(
        self,
        download_target,  # type: DownloadTarget
        download_dir,  # type: str
    ):
        # type: (...) -> DownloadObserver
        raise NotImplementedError()


def download(
    targets=Targets(),  # type: Targets
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    constraint_files=None,  # type: Optional[Iterable[str]]
    allow_prereleases=False,  # type: bool
    transitive=True,  # type: bool
    repos_configuration=ReposConfiguration(),  # type: ReposConfiguration
    resolver_version=None,  # type: Optional[ResolverVersion.Value]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    build_configuration=BuildConfiguration(),  # type: BuildConfiguration
    dest=None,  # type: Optional[str]
    max_parallel_jobs=None,  # type: Optional[int]
    observer=None,  # type: Optional[ResolveObserver]
    pip_log=None,  # type: Optional[PipLog]
    pip_version=None,  # type: Optional[PipVersionValue]
    resolver=None,  # type: Optional[Resolver]
    use_pip_config=False,  # type: bool
    extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
    keyring_provider=None,  # type: Optional[str]
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
    universal_targets=(),  # type: Iterable[UniversalTarget]
):
    # type: (...) -> Downloaded
    """Downloads all distributions needed to meet requirements for multiple distribution targets.

    :keyword targets: The distribution target environments to download for.
    :keyword requirements: A sequence of requirement strings.
    :keyword requirement_files: A sequence of requirement file paths.
    :keyword constraint_files: A sequence of constraint file paths.
    :keyword allow_prereleases: Whether to include pre-release and development versions when
      resolving requirements. Defaults to ``False``, but any requirements that explicitly request
      pre-release or development versions will override this setting.
    :keyword transitive: Whether to resolve transitive dependencies of requirements.
      Defaults to ``True``.
    :keyword repos_configuration: Configuration for package repositories to resolve packages from.
    :keyword resolver_version: The resolver version to use.
    :keyword network_configuration: Configuration for network requests made downloading and building
      distributions.
    :keyword build_configuration: The configuration for building resolved projects.
    :keyword dest: A directory path to download distributions to.
    :keyword max_parallel_jobs: The maximum number of parallel jobs to use when resolving,
      building and installing distributions in a resolve. Defaults to the number of CPUs available.
    :keyword observer: An optional observer of the download internals.
    :keyword pip_log: Preserve the `pip download` log and print its location to stderr.
      Defaults to ``False``.
    :returns: The local distributions meeting all requirements and constraints.
    :raises Unsatisfiable: If the resolution of download of distributions fails for any reason.
    :raises ValueError: If a foreign platform was provided in `platforms`, and `use_wheel=False`.
    :raises ValueError: If `build=False` and `use_wheel=False`.
    """
    direct_requirements = _parse_reqs(requirements, requirement_files, network_configuration)
    package_index_configuration = PackageIndexConfiguration.create(
        pip_version=pip_version,
        resolver_version=resolver_version,
        repos_configuration=repos_configuration,
        network_configuration=network_configuration,
        use_pip_config=use_pip_config,
        extra_pip_requirements=extra_pip_requirements,
        keyring_provider=keyring_provider,
    )
    build_requests, download_results = _download_internal(
        targets=targets,
        direct_requirements=direct_requirements,
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
        allow_prereleases=allow_prereleases,
        transitive=transitive,
        package_index_configuration=package_index_configuration,
        build_configuration=build_configuration,
        dest=dest,
        max_parallel_jobs=max_parallel_jobs,
        observer=observer,
        pip_log=pip_log,
        pip_version=pip_version,
        resolver=resolver,
        dependency_configuration=dependency_configuration,
        universal_targets=universal_targets,
    )

    local_distributions = []

    def add_build_requests(requests):
        # type: (Iterable[BuildRequest]) -> None
        for request in requests:
            local_distributions.append(
                LocalDistribution(
                    download_target=request.download_target,
                    path=request.source_path,
                    fingerprint=request.fingerprint,
                    subdirectory=request.subdirectory,
                )
            )

    add_build_requests(build_requests)
    for download_result in download_results:
        add_build_requests(download_result.build_requests())
        for install_request in download_result.install_requests():
            local_distributions.append(
                LocalDistribution(
                    download_target=install_request.download_target,
                    path=install_request.wheel_path,
                    fingerprint=install_request.fingerprint,
                )
            )

    return Downloaded(local_distributions=tuple(local_distributions))
