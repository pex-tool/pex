# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import functools
import hashlib
import itertools
import os
import zipfile
from collections import OrderedDict, defaultdict

from pex import targets
from pex.common import AtomicDirectory, atomic_directory, pluralize, safe_mkdtemp
from pex.dist_metadata import DistMetadata
from pex.fetcher import URLFetcher
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.jobs import Raise, SpawnedJob, execute_parallel
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName, distribution_satisfies_requirement
from pex.pex_info import PexInfo
from pex.pip.tool import PackageIndexConfiguration, get_pip
from pex.requirements import LocalProjectRequirement
from pex.resolve.locked_resolve import LockConfiguration, LockedResolve, LockRequest
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolved_requirement import ResolvedRequirement
from pex.resolve.resolver_configuration import ResolverVersion
from pex.resolve.resolvers import Installed, InstalledDistribution, Unsatisfiable, Untranslatable
from pex.targets import Target, Targets
from pex.third_party.pkg_resources import Requirement
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper, DistributionHelper

if TYPE_CHECKING:
    from typing import DefaultDict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

    import attr  # vendor:skip

    from pex.requirements import ParsedRequirement
else:
    from pex.third_party import attr


@attr.s
class _ResolveHandler(object):
    download_result = attr.ib()  # type: DownloadResult
    wheel_builder = attr.ib()  # type: WheelBuilder
    url_fetcher = attr.ib()  # type: URLFetcher
    max_parallel_jobs = attr.ib(default=None)  # type: Optional[int]

    def __call__(self, resolved_requirements):
        # type: (Iterable[ResolvedRequirement]) -> None
        self._resolved_requirements = resolved_requirements

    def lock(self):
        # type: () -> DownloadResult

        build_requests = tuple(self.download_result.build_requests())
        with TRACER.timed(
            "Building {count} source {distributions} to gather metadata for lock.".format(
                count=len(build_requests), distributions=pluralize(build_requests, "distribution")
            )
        ):
            build_results = self.wheel_builder.build_wheels(
                build_requests=build_requests,
                max_parallel_jobs=self.max_parallel_jobs,
            )
            dist_metadatas = tuple(
                DistMetadata.for_dist(install_request.wheel_path)
                for install_request in itertools.chain(
                    tuple(self.download_result.install_requests()),
                    itertools.chain.from_iterable(build_results.values()),
                )
            )
        locked_resolve = LockedResolve.create(
            self.download_result.target.platform.tag,
            self._resolved_requirements,
            dist_metadatas,
            self.url_fetcher,
        )
        return attr.evolve(self.download_result, locked_resolve=locked_resolve)


def _uniqued_targets(targets=None):
    # type: (Optional[Iterable[Target]]) -> Tuple[Target, ...]
    return tuple(OrderedSet(targets)) if targets is not None else ()


@attr.s(frozen=True)
class DownloadRequest(object):
    targets = attr.ib(converter=_uniqued_targets)  # type: Tuple[Target, ...]
    direct_requirements = attr.ib()  # type: Iterable[ParsedRequirement]
    requirements = attr.ib(default=None)  # type: Optional[Iterable[str]]
    requirement_files = attr.ib(default=None)  # type: Optional[Iterable[str]]
    constraint_files = attr.ib(default=None)  # type: Optional[Iterable[str]]
    allow_prereleases = attr.ib(default=False)  # type: bool
    transitive = attr.ib(default=True)  # type: bool
    package_index_configuration = attr.ib(default=None)  # type: Optional[PackageIndexConfiguration]
    cache = attr.ib(default=None)  # type: Optional[str]
    build = attr.ib(default=True)  # type: bool
    use_wheel = attr.ib(default=True)  # type: bool
    prefer_older_binary = attr.ib(default=False)  # type: bool
    use_pep517 = attr.ib(default=None)  # type: Optional[bool]
    build_isolation = attr.ib(default=True)  # type: bool
    lock_configuration = attr.ib(default=None)  # type: Optional[LockConfiguration]

    def iter_local_projects(self):
        # type: () -> Iterator[BuildRequest]
        for requirement in self.direct_requirements:
            if isinstance(requirement, LocalProjectRequirement):
                for target in self.targets:
                    yield BuildRequest.create(target=target, source_path=requirement.path)

    def download_distributions(self, dest=None, max_parallel_jobs=None):
        # type: (...) -> List[DownloadResult]
        if not self.requirements and not self.requirement_files:
            # Nothing to resolve.
            return []

        dest = dest or safe_mkdtemp()
        spawn_download = functools.partial(self._spawn_download, dest, max_parallel_jobs)
        with TRACER.timed("Resolving for:\n  {}".format("\n  ".join(map(str, self.targets)))):
            return list(
                execute_parallel(
                    inputs=self.targets,
                    spawn_func=spawn_download,
                    error_handler=Raise(Unsatisfiable),
                    max_jobs=max_parallel_jobs,
                )
            )

    def _spawn_download(
        self,
        resolved_dists_dir,  # type: str
        max_parallel_jobs,  # type: Optional[int]
        target,  # type: Target
    ):
        # type: (...) -> SpawnedJob[DownloadResult]
        download_dir = os.path.join(resolved_dists_dir, target.id)
        download_result = DownloadResult(target, download_dir)

        resolve_handler = None  # type: Optional[_ResolveHandler]
        resolve_request = None  # type: Optional[LockRequest]
        if self.lock_configuration:
            network_configuration = (
                self.package_index_configuration.network_configuration
                if self.package_index_configuration
                else NetworkConfiguration()
            )
            resolve_handler = _ResolveHandler(
                download_result=download_result,
                wheel_builder=WheelBuilder(
                    package_index_configuration=self.package_index_configuration,
                    cache=self.cache,
                    prefer_older_binary=self.prefer_older_binary,
                    use_pep517=self.use_pep517,
                    build_isolation=self.build_isolation,
                ),
                url_fetcher=URLFetcher(network_configuration, handle_file_urls=True),
                max_parallel_jobs=max_parallel_jobs,
            )
            resolve_request = LockRequest(
                lock_configuration=self.lock_configuration, resolve_handler=resolve_handler
            )

        download_job = get_pip(interpreter=target.get_interpreter()).spawn_download_distributions(
            download_dir=download_dir,
            requirements=self.requirements,
            requirement_files=self.requirement_files,
            constraint_files=self.constraint_files,
            allow_prereleases=self.allow_prereleases,
            transitive=self.transitive,
            target=target,
            package_index_configuration=self.package_index_configuration,
            cache=self.cache,
            build=self.build,
            use_wheel=self.use_wheel,
            prefer_older_binary=self.prefer_older_binary,
            use_pep517=self.use_pep517,
            build_isolation=self.build_isolation,
            lock_request=resolve_request,
        )

        result_func = resolve_handler.lock if resolve_handler else lambda: download_result
        return SpawnedJob.and_then(job=download_job, result_func=result_func)


@attr.s(frozen=True)
class DownloadResult(object):
    @staticmethod
    def _is_wheel(path):
        # type: (str) -> bool
        return os.path.isfile(path) and path.endswith(".whl")

    target = attr.ib()  # type: Target
    download_dir = attr.ib()  # type: str
    locked_resolve = attr.ib(default=None)  # type: Optional[LockedResolve]

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
                yield BuildRequest.create(target=self.target, source_path=distribution_path)

    def install_requests(self):
        # type: () -> Iterator[InstallRequest]
        for distribution_path in self._iter_distribution_paths():
            if self._is_wheel(distribution_path):
                yield InstallRequest.create(target=self.target, wheel_path=distribution_path)


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
    # See: https://github.com/pantsbuild/pex/issues/1655 for a general overview of these cache
    # structure concerns.
    hasher = hashlib.sha256

    if os.path.isdir(path):
        return CacheHelper.dir_hash(path, hasher=hasher)
    return CacheHelper.hash(path, hasher=hasher)


@attr.s(frozen=True)
class BuildRequest(object):
    @classmethod
    def create(
        cls,
        target,  # type: Target
        source_path,  # type: str
    ):
        # type: (...) -> BuildRequest
        fingerprint = fingerprint_path(source_path)
        return cls(target=target, source_path=source_path, fingerprint=fingerprint)

    @classmethod
    def from_local_distribution(cls, local_distribution):
        # type: (LocalDistribution) -> BuildRequest
        request = cls.create(target=local_distribution.target, source_path=local_distribution.path)
        if local_distribution.fingerprint and request.fingerprint != local_distribution.fingerprint:
            raise IntegrityError(
                "Source at {source_path} was expected to have fingerprint {expected_fingerprint} "
                "but found to have fingerprint {actual_fingerprint}.".format(
                    source_path=request.source_path,
                    expected_fingerprint=local_distribution.fingerprint,
                    actual_fingerprint=request.fingerprint,
                )
            )
        return request

    target = attr.ib()  # type: Target
    source_path = attr.ib()  # type: str
    fingerprint = attr.ib()  # type: str

    def result(self, dist_root):
        # type: (str) -> BuildResult
        return BuildResult.from_request(self, dist_root=dist_root)


@attr.s(frozen=True)
class BuildResult(object):
    @classmethod
    def from_request(
        cls,
        build_request,  # type: BuildRequest
        dist_root,  # type: str
    ):
        # type: (...) -> BuildResult
        dist_type = "sdists" if os.path.isfile(build_request.source_path) else "local_projects"

        # For the purposes of building a wheel from source, the product should be uniqued by the wheel
        # name which is unique on the host os up to the python and abi tags. In other words, the product
        # of a CPython 2.7.6 wheel build and a CPython 2.7.18 wheel build should be functionally
        # interchangeable if the two CPython interpreters have matching abis.
        interpreter = build_request.target.get_interpreter()
        target_tags = "{python_tag}-{abi_tag}".format(
            python_tag=interpreter.identity.python_tag, abi_tag=interpreter.identity.abi_tag
        )

        dist_dir = os.path.join(
            dist_root,
            dist_type,
            os.path.basename(build_request.source_path),
            build_request.fingerprint,
            target_tags,
        )
        return cls(request=build_request, atomic_dir=AtomicDirectory(dist_dir))

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

    def finalize_build(self):
        # type: () -> InstallRequest
        self._atomic_dir.finalize()
        wheels = os.listdir(self.dist_dir)
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
        wheel = wheels[0]
        return InstallRequest.create(self.request.target, os.path.join(self.dist_dir, wheel))


@attr.s(frozen=True)
class InstallRequest(object):
    @classmethod
    def from_local_distribution(cls, local_distribution):
        # type: (LocalDistribution) -> InstallRequest
        request = cls.create(target=local_distribution.target, wheel_path=local_distribution.path)
        if local_distribution.fingerprint and request.fingerprint != local_distribution.fingerprint:
            raise IntegrityError(
                "Wheel at {wheel_path} was expected to have fingerprint {expected_fingerprint} "
                "but found to have fingerprint {actual_fingerprint}.".format(
                    wheel_path=request.wheel_path,
                    expected_fingerprint=local_distribution.fingerprint,
                    actual_fingerprint=request.fingerprint,
                )
            )
        return request

    @classmethod
    def create(
        cls,
        target,  # type: Target
        wheel_path,  # type: str
    ):
        # type: (...) -> InstallRequest
        fingerprint = fingerprint_path(wheel_path)
        return cls(target=target, wheel_path=wheel_path, fingerprint=fingerprint)

    target = attr.ib()  # type: Target
    wheel_path = attr.ib()  # type: str
    fingerprint = attr.ib()  # type: str

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

    @property
    def build_chroot(self):
        # type: () -> str
        return self._atomic_dir.work_dir

    @property
    def install_chroot(self):
        # type: () -> str
        return self._atomic_dir.target_dir

    def finalize_install(self, install_requests):
        # type: (Iterable[InstallRequest]) -> Iterator[InstalledDistribution]
        self._atomic_dir.finalize()

        # The install_chroot is keyed by the hash of the wheel file (zip) we installed. Here we add
        # a key by the hash of the exploded wheel dir (the install_chroot). This latter key is used
        # by zipped PEXes at runtime to explode their wheel chroots to the filesystem. By adding
        # the key here we short-circuit the explode process for PEXes created and run on the same
        # machine.
        #
        # From a clean cache after building a simple pex this looks like:
        # $ rm -rf ~/.pex
        # $ python -mpex -c pex -o /tmp/pex.pex .
        # $ tree -L 4 ~/.pex/
        # /home/jsirois/.pex/
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
        #         └── pex-2.0.2-py2.py3-none-any.whl -> /home/jsirois/.pex/installed_wheels/2a594cef34d2e9109bad847358d57ac4615f81f4/pex-2.0.2-py2.py3-none-any.whl  # noqa
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
        # pex:     /home/jsirois/.pex/installed_wheels/2a594cef34d2e9109bad847358d57ac4615f81f4/pex-2.0.2-py2.py3-none-any.whl  # noqa
        # pex:   * /tmp/pex.pex/.bootstrap
        # pex:   * - paths that do not exist or will be imported via zipimport
        # pex.pex 2.0.2
        #
        wheel_dir_hash = fingerprint_path(self.install_chroot)
        runtime_key_dir = os.path.join(self._installation_root, wheel_dir_hash)
        with atomic_directory(runtime_key_dir, exclusive=False) as atomic_dir:
            if not atomic_dir.is_finalized():
                # Note: Create a relative path symlink between the two directories so that the
                # PEX_ROOT can be used within a chroot environment where the prefix of the path may
                # change between programs running inside and outside of the chroot.
                source_path = os.path.join(atomic_dir.work_dir, self.request.wheel_file)
                start_dir = os.path.dirname(source_path)
                relative_target_path = os.path.relpath(self.install_chroot, start_dir)
                os.symlink(relative_target_path, source_path)

        return self._iter_installed_distributions(install_requests, fingerprint=wheel_dir_hash)

    def _iter_installed_distributions(
        self,
        install_requests,  # type: Iterable[InstallRequest]
        fingerprint,  # type: str
    ):
        # type: (...) -> Iterator[InstalledDistribution]
        if self.is_installed:
            distribution = DistributionHelper.distribution_from_path(self.install_chroot)
            if distribution is None:
                raise AssertionError("No distribution could be found for {}.".format(self))
            for install_request in install_requests:
                yield InstalledDistribution(
                    target=install_request.target,
                    fingerprinted_distribution=FingerprintedDistribution(distribution, fingerprint),
                )


class WheelBuilder(object):
    def __init__(
        self,
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
        cache=None,  # type: Optional[str]
        prefer_older_binary=False,  # type: bool
        use_pep517=None,  # type: Optional[bool]
        build_isolation=True,  # type: bool
        verify_wheels=True,  # type: bool
    ):
        # type: (...) -> None
        self._package_index_configuration = package_index_configuration
        self._cache = cache
        self._prefer_older_binary = prefer_older_binary
        self._use_pep517 = use_pep517
        self._build_isolation = build_isolation
        self._verify_wheels = verify_wheels

    @staticmethod
    def _categorize_build_requests(
        build_requests,  # type: Iterable[BuildRequest]
        dist_root,  # type: str
    ):
        # type: (...) -> Tuple[Iterable[BuildRequest], DefaultDict[str, OrderedSet[InstallRequest]]]
        unsatisfied_build_requests = []
        build_results = defaultdict(
            OrderedSet
        )  # type: DefaultDict[str, OrderedSet[InstallRequest]]
        for build_request in build_requests:
            build_result = build_request.result(dist_root)
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
                build_results[build_request.source_path].add(build_result.finalize_build())
        return unsatisfied_build_requests, build_results

    def _spawn_wheel_build(
        self,
        built_wheels_dir,  # type: str
        build_request,  # type: BuildRequest
    ):
        # type: (...) -> SpawnedJob[BuildResult]
        build_result = build_request.result(built_wheels_dir)
        build_job = get_pip(interpreter=build_request.target.get_interpreter()).spawn_build_wheels(
            distributions=[build_request.source_path],
            wheel_dir=build_result.build_dir,
            cache=self._cache,
            package_index_configuration=self._package_index_configuration,
            interpreter=build_request.target.get_interpreter(),
            prefer_older_binary=self._prefer_older_binary,
            use_pep517=self._use_pep517,
            build_isolation=self._build_isolation,
            verify=self._verify_wheels,
        )
        return SpawnedJob.wait(job=build_job, result=build_result)

    def build_wheels(
        self,
        build_requests,  # type: Iterable[BuildRequest]
        workspace=None,  # type: Optional[str]
        max_parallel_jobs=None,  # type: Optional[int]
    ):
        # type: (...) -> Mapping[str, OrderedSet[InstallRequest]]

        if not build_requests:
            # Nothing to build or install.
            return {}

        cache = self._cache or workspace or safe_mkdtemp()

        built_wheels_dir = os.path.join(cache, "built_wheels")
        spawn_wheel_build = functools.partial(self._spawn_wheel_build, built_wheels_dir)

        with TRACER.timed(
            "Building distributions for:" "\n  {}".format("\n  ".join(map(str, build_requests)))
        ):
            build_requests, build_results = self._categorize_build_requests(
                build_requests=build_requests, dist_root=built_wheels_dir
            )

            for build_result in execute_parallel(
                inputs=build_requests,
                spawn_func=spawn_wheel_build,
                error_handler=Raise(Untranslatable),
                max_jobs=max_parallel_jobs,
            ):
                build_results[build_result.request.source_path].add(build_result.finalize_build())

        return build_results


class BuildAndInstallRequest(object):
    def __init__(
        self,
        build_requests,  # type: Iterable[BuildRequest]
        install_requests,  # type:  Iterable[InstallRequest]
        direct_requirements=None,  # type: Optional[Iterable[ParsedRequirement]]
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
        cache=None,  # type: Optional[str]
        compile=False,  # type: bool
        prefer_older_binary=False,  # type: bool
        use_pep517=None,  # type: Optional[bool]
        build_isolation=True,  # type: bool
        verify_wheels=True,  # type: bool
    ):
        # type: (...) -> None
        self._build_requests = tuple(build_requests)
        self._install_requests = tuple(install_requests)
        self._direct_requirements = tuple(direct_requirements or ())
        self._cache = cache
        self._compile = compile
        self._wheel_builder = WheelBuilder(
            package_index_configuration=package_index_configuration,
            cache=self._cache,
            prefer_older_binary=prefer_older_binary,
            use_pep517=use_pep517,
            build_isolation=build_isolation,
            verify_wheels=verify_wheels,
        )

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

    def _spawn_install(
        self,
        installed_wheels_dir,  # type: str
        install_request,  # type: InstallRequest
    ):
        # type: (...) -> SpawnedJob[InstallResult]
        install_result = install_request.result(installed_wheels_dir)
        install_job = get_pip(
            interpreter=install_request.target.get_interpreter()
        ).spawn_install_wheel(
            wheel=install_request.wheel_path,
            install_dir=install_result.build_chroot,
            compile=self._compile,
            cache=self._cache,
            target=install_request.target,
        )
        return SpawnedJob.wait(job=install_job, result=install_result)

    def install_distributions(
        self,
        ignore_errors=False,  # type: bool
        workspace=None,  # type: Optional[str]
        max_parallel_jobs=None,  # type: Optional[int]
    ):
        # type: (...) -> Iterable[InstalledDistribution]
        if not any((self._build_requests, self._install_requests)):
            # Nothing to build or install.
            return ()

        cache = self._cache or workspace or safe_mkdtemp()

        installed_wheels_dir = os.path.join(cache, PexInfo.INSTALL_CACHE)
        spawn_install = functools.partial(self._spawn_install, installed_wheels_dir)

        to_install = list(self._install_requests)
        installations = []  # type: List[InstalledDistribution]

        # 1. Build local projects and sdists.
        build_results = self._wheel_builder.build_wheels(
            build_requests=self._build_requests,
            workspace=workspace,
            max_parallel_jobs=max_parallel_jobs,
        )
        to_install.extend(itertools.chain.from_iterable(build_results.values()))

        # 2. All requirements are now in wheel form: calculate any missing direct requirement
        #    project names from the wheel names.
        with TRACER.timed(
            "Calculating project names for direct requirements:"
            "\n  {}".format("\n  ".join(map(str, self._direct_requirements)))
        ):

            def iter_direct_requirements():
                # type: () -> Iterator[Requirement]
                for requirement in self._direct_requirements:
                    if not isinstance(requirement, LocalProjectRequirement):
                        yield requirement.requirement
                        continue

                    install_reqs = build_results.get(requirement.path)
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
                                        for path, build_results in build_results.items()
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
                direct_requirements_by_project_name[ProjectName(direct_requirement)].add(
                    direct_requirement
                )

        # 3. Install wheels in individual chroots.

        # Dedup by wheel name; e.g.: only install universal wheels once even though they'll get
        # downloaded / built for each interpreter or platform.
        install_requests_by_wheel_file = (
            OrderedDict()
        )  # type: OrderedDict[str, List[InstallRequest]]
        for install_request in to_install:
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

            for install_result in execute_parallel(
                inputs=install_requests,
                spawn_func=spawn_install,
                error_handler=Raise(Untranslatable),
                max_jobs=max_parallel_jobs,
            ):
                add_installation(install_result)

        if not ignore_errors:
            with TRACER.timed("Checking install"):
                self._check_install(installations)

        installed_distributions = OrderedSet()  # type: OrderedSet[InstalledDistribution]
        for installed_distribution in installations:
            distribution = installed_distribution.distribution
            direct_reqs = [
                req
                for req in direct_requirements_by_project_name[ProjectName(distribution)]
                if distribution_satisfies_requirement(distribution, req)
                and installed_distribution.target.requirement_applies(req)
            ]
            installed_distributions.add(
                installed_distribution.with_direct_requirements(direct_requirements=direct_reqs)
            )
        return installed_distributions

    @staticmethod
    def _check_install(installed_distributions):
        # type: (Iterable[InstalledDistribution]) -> None
        installed_distribution_by_project_name = OrderedDict(
            (ProjectName(resolved_distribution.distribution), resolved_distribution)
            for resolved_distribution in installed_distributions
        )  # type: OrderedDict[ProjectName, InstalledDistribution]

        unsatisfied = []
        for installed_distribution in installed_distribution_by_project_name.values():
            dist = installed_distribution.distribution
            target = installed_distribution.target
            for requirement in dist.requires():
                if not target.requirement_applies(requirement):
                    continue

                installed_requirement_dist = installed_distribution_by_project_name.get(
                    ProjectName(requirement)
                )
                if not installed_requirement_dist:
                    unsatisfied.append(
                        "{dist} requires {requirement} but no version was resolved".format(
                            dist=dist.as_requirement(), requirement=requirement
                        )
                    )
                else:
                    installed_dist = installed_requirement_dist.distribution
                    if installed_dist not in requirement:
                        unsatisfied.append(
                            "{dist} requires {requirement} but {resolved_dist} was resolved".format(
                                dist=dist.as_requirement(),
                                requirement=requirement,
                                resolved_dist=installed_dist,
                            )
                        )

        if unsatisfied:
            raise Unsatisfiable(
                "Failed to resolve compatible distributions:\n{failures}".format(
                    failures="\n".join(
                        "{index}: {failure}".format(index=index + 1, failure=failure)
                        for index, failure in enumerate(unsatisfied)
                    )
                )
            )


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
    indexes=None,  # type: Optional[Sequence[str]]
    find_links=None,  # type: Optional[Sequence[str]]
    resolver_version=None,  # type: Optional[ResolverVersion.Value]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    cache=None,  # type: Optional[str]
    build=True,  # type: bool
    use_wheel=True,  # type: bool
    prefer_older_binary=False,  # type: bool
    use_pep517=None,  # type: Optional[bool]
    build_isolation=True,  # type: bool
    compile=False,  # type: bool
    max_parallel_jobs=None,  # type: Optional[int]
    ignore_errors=False,  # type: bool
    verify_wheels=True,  # type: bool
    lock_configuration=None,  # type: Optional[LockConfiguration]
):
    # type: (...) -> Installed
    """Resolves all distributions needed to meet requirements for multiple distribution targets.

    The resulting distributions are installed in individual chroots that can be independently added
    to `sys.path`

    :keyword targets: The distribution target environments to resolve for.
    :keyword requirements: A sequence of requirement strings.
    :keyword requirement_files: A sequence of requirement file paths.
    :keyword constraint_files: A sequence of constraint file paths.
    :keyword allow_prereleases: Whether to include pre-release and development versions when
      resolving requirements. Defaults to ``False``, but any requirements that explicitly request
      prerelease or development versions will override this setting.
    :keyword transitive: Whether to resolve transitive dependencies of requirements.
      Defaults to ``True``.
    :keyword indexes: A list of urls or paths pointing to PEP 503 compliant repositories to search for
      distributions. Defaults to ``None`` which indicates to use the default pypi index. To turn off
      use of all indexes, pass an empty list.
    :keyword find_links: A list or URLs, paths to local html files or directory paths. If URLs or
      local html file paths, these are parsed for links to distributions. If a local directory path,
      its listing is used to discover distributions.
    :keyword resolver_version: The resolver version to use.
    :keyword network_configuration: Configuration for network requests made downloading and building
      distributions.
    :keyword cache: A directory path to use to cache distributions locally.
    :keyword build: Whether to allow building source distributions when no wheel is found.
      Defaults to ``True``.
    :keyword use_wheel: Whether to allow resolution of pre-built wheel distributions.
      Defaults to ``True``.
    :keyword prefer_older_binary: Whether to prefer older binary distributions to newer source
      distributions (avoid building wheels when possible). Defaults to ``False``.
    :keyword use_pep517: Whether to force use of PEP 517 for building source distributions into
      wheels or force direct invocation of ``setup.py bdist_wheel``. Defaults to using PEP-517 only
      when a ``pyproject.toml`` file is present with a ``build-system`` section.
    :keyword build_isolation: Disable ``sys.path`` isolation when building a modern source
      distribution. Build dependencies specified by PEP 518 must already be installed on the
      ``sys.path`` if `build_isolation` is ``True``.
    :keyword compile: Whether to pre-compile resolved distribution python sources.
      Defaults to ``False``.
    :keyword max_parallel_jobs: The maximum number of parallel jobs to use when resolving,
      building and installing distributions in a resolve. Defaults to the number of CPUs available.
    :keyword ignore_errors: Whether to ignore resolution solver errors. Defaults to ``False``.
    :keyword verify_wheels: Whether to verify wheels have valid metadata. Defaults to ``True``.
    :keyword lock_configuration: If a lock should be generated for the resolve - its configuration.
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
    # distributions and then `pip install` to install each distribution in its own chroot.
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
    workspace = safe_mkdtemp()
    package_index_configuration = PackageIndexConfiguration.create(
        resolver_version=resolver_version,
        indexes=indexes,
        find_links=find_links,
        network_configuration=network_configuration,
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
        cache=cache,
        build=build,
        use_wheel=use_wheel,
        prefer_older_binary=prefer_older_binary,
        use_pep517=use_pep517,
        build_isolation=build_isolation,
        dest=workspace,
        max_parallel_jobs=max_parallel_jobs,
        lock_configuration=lock_configuration,
    )

    install_requests = []  # type: List[InstallRequest]
    locks = []  # type: List[LockedResolve]
    for download_result in download_results:
        if download_result.locked_resolve:
            locks.append(download_result.locked_resolve)
        build_requests.extend(download_result.build_requests())
        install_requests.extend(download_result.install_requests())

    build_and_install_request = BuildAndInstallRequest(
        build_requests=build_requests,
        install_requests=install_requests,
        direct_requirements=direct_requirements,
        package_index_configuration=package_index_configuration,
        cache=cache,
        compile=compile,
        prefer_older_binary=prefer_older_binary,
        use_pep517=use_pep517,
        build_isolation=build_isolation,
        verify_wheels=verify_wheels,
    )

    ignore_errors = ignore_errors or not transitive
    installed_distributions = tuple(
        build_and_install_request.install_distributions(
            ignore_errors=ignore_errors, workspace=workspace, max_parallel_jobs=max_parallel_jobs
        )
    )
    return Installed(installed_distributions=installed_distributions, locks=tuple(locks))


def _download_internal(
    targets,  # type: Targets
    direct_requirements,  # type: Iterable[ParsedRequirement]
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    constraint_files=None,  # type: Optional[Iterable[str]]
    allow_prereleases=False,  # type: bool
    transitive=True,  # type: bool
    package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
    cache=None,  # type: Optional[str]
    build=True,  # type: bool
    use_wheel=True,  # type: bool
    prefer_older_binary=False,  # type: bool
    use_pep517=None,  # type: Optional[bool]
    build_isolation=True,  # type: bool
    dest=None,  # type: Optional[str]
    max_parallel_jobs=None,  # type: Optional[int]
    lock_configuration=None,  # type: Optional[LockConfiguration]
):
    # type: (...) -> Tuple[List[BuildRequest], List[DownloadResult]]

    unique_targets = targets.unique_targets()
    download_request = DownloadRequest(
        targets=unique_targets,
        direct_requirements=direct_requirements,
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
        allow_prereleases=allow_prereleases,
        transitive=transitive,
        package_index_configuration=package_index_configuration,
        cache=cache,
        build=build,
        use_wheel=use_wheel,
        prefer_older_binary=prefer_older_binary,
        use_pep517=use_pep517,
        build_isolation=build_isolation,
        lock_configuration=lock_configuration,
    )

    local_projects = list(download_request.iter_local_projects())

    dest = dest or safe_mkdtemp()
    download_results = download_request.download_distributions(
        dest=dest, max_parallel_jobs=max_parallel_jobs
    )
    return local_projects, download_results


@attr.s(frozen=True)
class LocalDistribution(object):
    path = attr.ib()  # type: str
    fingerprint = attr.ib()  # type: str
    target = attr.ib(default=targets.current())  # type: Target

    @fingerprint.default
    def _calculate_fingerprint(self):
        return fingerprint_path(self.path)

    @property
    def is_wheel(self):
        return self.path.endswith(".whl") and zipfile.is_zipfile(self.path)


@attr.s(frozen=True)
class Downloaded(object):
    local_distributions = attr.ib()  # type: Tuple[LocalDistribution, ...]
    locked_resolves = attr.ib(default=())  # type: Tuple[LockedResolve, ...]


def download(
    targets=Targets(),  # type: Targets
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    constraint_files=None,  # type: Optional[Iterable[str]]
    allow_prereleases=False,  # type: bool
    transitive=True,  # type: bool
    indexes=None,  # type: Optional[Sequence[str]]
    find_links=None,  # type: Optional[Sequence[str]]
    resolver_version=None,  # type: Optional[ResolverVersion.Value]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    cache=None,  # type: Optional[str]
    build=True,  # type: bool
    use_wheel=True,  # type: bool
    prefer_older_binary=False,  # type: bool
    use_pep517=None,  # type: Optional[bool]
    build_isolation=True,  # type: bool
    dest=None,  # type: Optional[str]
    max_parallel_jobs=None,  # type: Optional[int]
    lock_configuration=None,  # type: Optional[LockConfiguration]
):
    # type: (...) -> Downloaded
    """Downloads all distributions needed to meet requirements for multiple distribution targets.

    :keyword targets: The distribution target environments to download for.
    :keyword requirements: A sequence of requirement strings.
    :keyword requirement_files: A sequence of requirement file paths.
    :keyword constraint_files: A sequence of constraint file paths.
    :keyword allow_prereleases: Whether to include pre-release and development versions when
      resolving requirements. Defaults to ``False``, but any requirements that explicitly request
      prerelease or development versions will override this setting.
    :keyword transitive: Whether to resolve transitive dependencies of requirements.
      Defaults to ``True``.
    :keyword indexes: A list of urls or paths pointing to PEP 503 compliant repositories to search
      for distributions. Defaults to ``None`` which indicates to use the default pypi index. To turn
      off use of all indexes, pass an empty list.
    :keyword find_links: A list of URLs, paths to local html files or directory paths. If URLs or
      local html file paths, these are parsed for links to distributions. If a local directory path,
      its listing is used to discover distributions.
    :keyword resolver_version: The resolver version to use.
    :keyword network_configuration: Configuration for network requests made downloading and building
      distributions.
    :keyword cache: A directory path to use to cache distributions locally.
    :keyword build: Whether to allow building source distributions when no wheel is found.
      Defaults to ``True``.
    :keyword use_wheel: Whether to allow resolution of pre-built wheel distributions.
      Defaults to ``True``.
    :keyword prefer_older_binary: Whether to prefer older binary distributions to newer source
      distributions (avoid building wheels when possible). Defaults to ``False``.
    :keyword use_pep517: Whether to force use of PEP 517 for building source distributions into
      wheels or force direct invocation of ``setup.py bdist_wheel``. Defaults to using PEP-517 only
      when a ``pyproject.toml`` file is present with a ``build-system`` section.
    :keyword build_isolation: Disable ``sys.path`` isolation when building a modern source
      distribution. Build dependencies specified by PEP 518 must already be installed on the
      ``sys.path`` if `build_isolation` is ``True``.
    :keyword dest: A directory path to download distributions to.
    :keyword max_parallel_jobs: The maximum number of parallel jobs to use when resolving,
      building and installing distributions in a resolve. Defaults to the number of CPUs available.
    :keyword lock_configuration: If a lock should be generated for the download - its configuration.
    :returns: The local distributions meeting all requirements and constraints.
    :raises Unsatisfiable: If the resolution of download of distributions fails for any reason.
    :raises ValueError: If a foreign platform was provided in `platforms`, and `use_wheel=False`.
    :raises ValueError: If `build=False` and `use_wheel=False`.
    """
    direct_requirements = _parse_reqs(requirements, requirement_files, network_configuration)
    package_index_configuration = PackageIndexConfiguration.create(
        resolver_version=resolver_version,
        indexes=indexes,
        find_links=find_links,
        network_configuration=network_configuration,
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
        cache=cache,
        build=build,
        use_wheel=use_wheel,
        prefer_older_binary=prefer_older_binary,
        use_pep517=use_pep517,
        build_isolation=build_isolation,
        dest=dest,
        max_parallel_jobs=max_parallel_jobs,
        lock_configuration=lock_configuration,
    )

    local_distributions = []
    locked_resolves = []

    def add_build_requests(requests):
        # type: (Iterable[BuildRequest]) -> None
        for request in requests:
            local_distributions.append(
                LocalDistribution(
                    target=request.target,
                    path=request.source_path,
                    fingerprint=request.fingerprint,
                )
            )

    add_build_requests(build_requests)
    for download_result in download_results:
        if download_result.locked_resolve:
            locked_resolves.append(download_result.locked_resolve)
        add_build_requests(download_result.build_requests())
        for install_request in download_result.install_requests():
            local_distributions.append(
                LocalDistribution(
                    target=install_request.target,
                    path=install_request.wheel_path,
                    fingerprint=install_request.fingerprint,
                )
            )

    return Downloaded(
        local_distributions=tuple(local_distributions), locked_resolves=tuple(locked_resolves)
    )


def install(
    local_distributions,  # type: Iterable[LocalDistribution]
    indexes=None,  # type: Optional[Sequence[str]]
    find_links=None,  # type: Optional[Iterable[str]]
    resolver_version=None,  # type: Optional[ResolverVersion.Value]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    cache=None,  # type: Optional[str]
    compile=False,  # type: bool
    max_parallel_jobs=None,  # type: Optional[int]
    ignore_errors=False,  # type: bool
    verify_wheels=True,  # type: bool
):
    # type: (...) -> List[InstalledDistribution]
    """Installs distributions in individual chroots that can be independently added to `sys.path`.

    :keyword local_distributions: The local distributions to install.
    :keyword indexes: A list of urls or paths pointing to PEP 503 compliant repositories to search for
      distributions. Defaults to ``None`` which indicates to use the default pypi index. To turn off
      use of all indexes, pass an empty list.
    :keyword find_links: A list or URLs, paths to local html files or directory paths. If URLs or
      local html file paths, these are parsed for links to distributions. If a local directory path,
      its listing is used to discover distributions.
    :keyword resolver_version: The resolver version to use.
    :keyword network_configuration: Configuration for network requests made downloading and building
      distributions.
    :keyword cache: A directory path to use to cache distributions locally.
    :keyword compile: Whether to pre-compile resolved distribution python sources.
      Defaults to ``False``.
    :keyword max_parallel_jobs: The maximum number of parallel jobs to use when resolving,
      building and installing distributions in a resolve. Defaults to the number of CPUs available.
    :keyword ignore_errors: Whether to ignore resolution solver errors. Defaults to ``False``.
    :keyword verify_wheels: Whether to verify wheels have valid metadata. Defaults to ``True``.
    :returns: The installed distributions meeting all requirements and constraints.
    :raises Untranslatable: If no compatible distributions could be acquired for
      a particular requirement.
    :raises Unsatisfiable: If not ignoring errors and distribution requirements are found to not be
      transitively satisfiable.
    """

    build_requests = []
    install_requests = []
    for local_distribution in local_distributions:
        if local_distribution.is_wheel:
            install_requests.append(InstallRequest.from_local_distribution(local_distribution))
        else:
            build_requests.append(BuildRequest.from_local_distribution(local_distribution))

    package_index_configuration = PackageIndexConfiguration.create(
        resolver_version=resolver_version,
        indexes=indexes,
        find_links=find_links,
        network_configuration=network_configuration,
    )
    build_and_install_request = BuildAndInstallRequest(
        build_requests=build_requests,
        install_requests=install_requests,
        package_index_configuration=package_index_configuration,
        cache=cache,
        compile=compile,
        verify_wheels=verify_wheels,
    )

    return list(
        build_and_install_request.install_distributions(
            ignore_errors=ignore_errors, max_parallel_jobs=max_parallel_jobs
        )
    )
