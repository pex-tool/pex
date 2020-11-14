# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import functools
import json
import os
import subprocess
import zipfile
from collections import OrderedDict, defaultdict, namedtuple
from textwrap import dedent

from pex import dist_metadata
from pex.common import AtomicDirectory, atomic_directory, safe_mkdtemp
from pex.distribution_target import DistributionTarget
from pex.interpreter import spawn_python_job
from pex.jobs import Raise, SpawnedJob, execute_parallel
from pex.orderedset import OrderedSet
from pex.pex_info import PexInfo
from pex.pip import PackageIndexConfiguration, get_pip
from pex.platforms import Platform
from pex.requirements import local_project_from_requirement, local_projects_from_requirement_file
from pex.third_party.packaging.markers import Marker
from pex.third_party.packaging.version import Version
from pex.third_party.packaging.version import parse as parse_version
from pex.third_party.pkg_resources import Distribution, Environment, Requirement
from pex.tracer import TRACER
from pex.util import CacheHelper


class Untranslatable(Exception):
    pass


class Unsatisfiable(Exception):
    pass


class InstalledDistribution(
    namedtuple("InstalledDistribution", ["target", "requirement", "distribution"])
):
    """A distribution target, requirement and the installed distribution that satisfies them
    both."""

    def __new__(cls, target, requirement, distribution):
        assert isinstance(target, DistributionTarget)
        assert isinstance(requirement, Requirement)
        assert isinstance(distribution, Distribution)
        return super(InstalledDistribution, cls).__new__(cls, target, requirement, distribution)


# A type alias to preserve API compatibility for resolve and resolve_multi.
ResolvedDistribution = InstalledDistribution


class DistributionRequirements(object):
    class Request(namedtuple("DistributionRequirementsRequest", ["target", "distributions"])):
        def spawn_calculation(self):
            search_path = [dist.location for dist in self.distributions]

            program = dedent(
                """
                import json
                import sys
                from collections import defaultdict
                from pkg_resources import Environment
        
        
                env = Environment(search_path={search_path!r})
                dependency_requirements = []
                for key in env:
                    for dist in env[key]:
                        dependency_requirements.extend(str(req) for req in dist.requires())
                json.dump(dependency_requirements, sys.stdout)
                """.format(
                    search_path=search_path
                )
            )

            job = spawn_python_job(
                args=["-c", program],
                stdout=subprocess.PIPE,
                interpreter=self.target.get_interpreter(),
                expose=["setuptools"],
            )
            return SpawnedJob.stdout(job=job, result_func=self._markers_by_requirement)

        @staticmethod
        def _markers_by_requirement(stdout):
            dependency_requirements = json.loads(stdout.decode("utf-8"))
            markers_by_req_key = defaultdict(OrderedSet)
            for requirement in dependency_requirements:
                req = Requirement.parse(requirement)
                if req.marker:
                    markers_by_req_key[req.key].add(req.marker)
            return markers_by_req_key

    @classmethod
    def merged(cls, markers_by_requirement_key_iter):
        markers_by_requirement_key = defaultdict(OrderedSet)
        for distribution_markers in markers_by_requirement_key_iter:
            for requirement, markers in distribution_markers.items():
                markers_by_requirement_key[requirement].update(markers)
        return cls(markers_by_requirement_key)

    def __init__(self, markers_by_requirement_key):
        self._markers_by_requirement_key = markers_by_requirement_key

    def to_requirement(self, dist):
        req = dist.as_requirement()

        # pkg_resources.Distribution.as_requirement returns requirements in one of two forms:
        # 1.) project_name==version
        # 2.) project_name===version
        # The latter form is used whenever the distribution's version is non-standard. In those
        # cases we cannot append environment markers since `===` indicates a raw version string to
        # the right that should not be parsed and instead should be compared literally in full.
        # See:
        # + https://www.python.org/dev/peps/pep-0440/#arbitrary-equality
        # + https://github.com/pantsbuild/pex/issues/940
        operator, _ = req.specs[0]
        if operator == "===":
            return req

        markers = OrderedSet()

        # Here we map any wheel python requirement to the equivalent environment marker:
        # See:
        # + https://www.python.org/dev/peps/pep-0345/#requires-python
        # + https://www.python.org/dev/peps/pep-0508/#environment-markers
        python_requires = dist_metadata.requires_python(dist)
        if python_requires:

            def choose_marker(version):
                # type: (str) -> str
                parsed_version = parse_version(version)
                if type(parsed_version) != Version or len(parsed_version.release) > 2:
                    return "python_full_version"
                else:
                    return "python_version"

            markers.update(
                Marker(python_version)
                for python_version in sorted(
                    "{marker} {operator} {version!r}".format(
                        marker=choose_marker(specifier.version),
                        operator=specifier.operator,
                        version=specifier.version,
                    )
                    for specifier in python_requires
                )
            )

        markers.update(self._markers_by_requirement_key.get(req.key, ()))

        if not markers:
            return req

        if len(markers) == 1:
            marker = next(iter(markers))
            req.marker = marker
            return req

        # We may have resolved with multiple paths to the dependency represented by dist and at least
        # two of those paths had (different) conditional requirements for dist based on environment
        # marker predicates. In that case, since the pip resolve succeeded, the implication is that the
        # environment markers are compatible; i.e.: their intersection selects the target interpreter.
        # Here we make that intersection explicit.
        # See: https://www.python.org/dev/peps/pep-0508/#grammar
        marker = " and ".join("({})".format(marker) for marker in markers)
        return Requirement.parse("{}; {}".format(req, marker))


def parsed_platform(platform=None):
    """Parse the given platform into a `Platform` object.

    Unlike `Platform.create`, this function supports the special platform of 'current' or `None`. This
    maps to the platform of any local python interpreter.

    :param platform: The platform string to parse. If `None` or 'current', return `None`. If already a
                     `Platform` object, return it.
    :type platform: str or :class:`Platform`
    :return: The parsed platform or `None` for the current platform.
    :rtype: :class:`Platform` or :class:`NoneType`
    """
    return Platform.create(platform) if platform and platform != "current" else None


class DownloadRequest(
    namedtuple(
        "DownloadRequest",
        [
            "targets",
            "requirements",
            "requirement_files",
            "constraint_files",
            "allow_prereleases",
            "transitive",
            "package_index_configuration",
            "cache",
            "build",
            "use_wheel",
            "manylinux",
        ],
    )
):
    def iter_local_projects(self):
        if self.requirements:
            for req in self.requirements:
                local_project = local_project_from_requirement(req)
                if local_project:
                    for target in self.targets:
                        yield BuildRequest.create(target=target, source_path=local_project)

        if self.requirement_files:
            for requirement_file in self.requirement_files:
                for local_project in local_projects_from_requirement_file(requirement_file):
                    for target in self.targets:
                        yield BuildRequest.create(target=target, source_path=local_project)

    def download_distributions(self, dest=None, max_parallel_jobs=None):
        if not self.requirements and not self.requirement_files:
            # Nothing to resolve.
            return None

        dest = dest or safe_mkdtemp()
        spawn_download = functools.partial(self._spawn_download, dest)
        with TRACER.timed("Resolving for:\n  {}".format("\n  ".join(map(str, self.targets)))):
            return list(
                execute_parallel(
                    inputs=self.targets,
                    spawn_func=spawn_download,
                    error_handler=Raise(Unsatisfiable),
                    max_jobs=max_parallel_jobs,
                )
            )

    def _spawn_download(self, resolved_dists_dir, target):
        download_dir = os.path.join(resolved_dists_dir, target.id)
        download_job = get_pip().spawn_download_distributions(
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
            manylinux=self.manylinux,
            use_wheel=self.use_wheel,
        )
        return SpawnedJob.wait(job=download_job, result=DownloadResult(target, download_dir))


class DownloadResult(namedtuple("DownloadResult", ["target", "download_dir"])):
    @staticmethod
    def _is_wheel(path):
        return os.path.isfile(path) and path.endswith(".whl")

    def _iter_distribution_paths(self):
        if not os.path.exists(self.download_dir):
            return
        for distribution in os.listdir(self.download_dir):
            yield os.path.join(self.download_dir, distribution)

    def build_requests(self):
        for distribution_path in self._iter_distribution_paths():
            if not self._is_wheel(distribution_path):
                yield BuildRequest.create(target=self.target, source_path=distribution_path)

    def install_requests(self):
        for distribution_path in self._iter_distribution_paths():
            if self._is_wheel(distribution_path):
                yield InstallRequest.create(target=self.target, wheel_path=distribution_path)


class IntegrityError(Exception):
    pass


def fingerprint_path(path):
    hasher = CacheHelper.dir_hash if os.path.isdir(path) else CacheHelper.hash
    return hasher(path)


class BuildRequest(namedtuple("BuildRequest", ["target", "source_path", "fingerprint"])):
    @classmethod
    def create(cls, target, source_path):
        fingerprint = fingerprint_path(source_path)
        return cls(target=target, source_path=source_path, fingerprint=fingerprint)

    @classmethod
    def from_local_distribution(cls, local_distribution):
        request = cls.create(target=local_distribution.target, source_path=local_distribution.path)
        if local_distribution.fingerprint and request.fingerprint != local_distribution.fingerprint:
            raise IntegrityError(
                "Source at {source_path} was expected to have fingerprint {expected_fingerprint} but found "
                "to have fingerprint {actual_fingerprint}.".format(
                    source_path=request.source_path,
                    expected_fingerprint=local_distribution.fingerprint,
                    actual_fingerprint=request.fingerprint,
                )
            )
        return request

    def result(self, dist_root):
        return BuildResult.from_request(self, dist_root=dist_root)


class BuildResult(namedtuple("BuildResult", ["request", "atomic_dir"])):
    @classmethod
    def from_request(cls, build_request, dist_root):
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

    @property
    def is_built(self):
        return self.atomic_dir.is_finalized

    @property
    def build_dir(self):
        return self.atomic_dir.work_dir

    @property
    def dist_dir(self):
        return self.atomic_dir.target_dir

    def finalize_build(self):
        self.atomic_dir.finalize()
        for wheel in os.listdir(self.dist_dir):
            yield InstallRequest.create(self.request.target, os.path.join(self.dist_dir, wheel))


class InstallRequest(namedtuple("InstallRequest", ["target", "wheel_path", "fingerprint"])):
    @classmethod
    def from_local_distribution(cls, local_distribution):
        request = cls.create(target=local_distribution.target, wheel_path=local_distribution.path)
        if local_distribution.fingerprint and request.fingerprint != local_distribution.fingerprint:
            raise IntegrityError(
                "Wheel at {wheel_path} was expected to have fingerprint {expected_fingerprint} but found "
                "to have fingerprint {actual_fingerprint}.".format(
                    wheel_path=request.wheel_path,
                    expected_fingerprint=local_distribution.fingerprint,
                    actual_fingerprint=request.fingerprint,
                )
            )
        return request

    @classmethod
    def create(cls, target, wheel_path):
        fingerprint = fingerprint_path(wheel_path)
        return cls(target=target, wheel_path=wheel_path, fingerprint=fingerprint)

    @property
    def wheel_file(self):
        return os.path.basename(self.wheel_path)

    def result(self, installation_root):
        return InstallResult.from_request(self, installation_root=installation_root)


class InstallResult(namedtuple("InstallResult", ["request", "installation_root", "atomic_dir"])):
    @classmethod
    def from_request(cls, install_request, installation_root):
        install_chroot = os.path.join(
            installation_root, install_request.fingerprint, install_request.wheel_file
        )
        return cls(
            request=install_request,
            installation_root=installation_root,
            atomic_dir=AtomicDirectory(install_chroot),
        )

    @property
    def is_installed(self):
        return self.atomic_dir.is_finalized

    @property
    def build_chroot(self):
        return self.atomic_dir.work_dir

    @property
    def install_chroot(self):
        return self.atomic_dir.target_dir

    def finalize_install(self, install_requests):
        self.atomic_dir.finalize()

        # The install_chroot is keyed by the hash of the wheel file (zip) we installed. Here we add a
        # key by the hash of the exploded wheel dir (the install_chroot). This latter key is used by
        # zipped PEXes at runtime to explode their wheel chroots to the filesystem. By adding the key
        # here we short-circuit the explode process for PEXes created and run on the same machine.
        #
        # From a clean cache after building a simple pex this looks like:
        # $ rm -rf ~/.pex
        # $ python -mpex -c pex -o /tmp/pex.pex .
        # $ tree -L 4 ~/.pex/
        # /home/jsirois/.pex/
        # ├── built_wheels
        # │   └── 1003685de2c3604dc6daab9540a66201c1d1f718
        # │       └── cp-38-cp38
        # │           └── pex-2.0.2-py2.py3-none-any.whl
        # └── installed_wheels
        #     ├── 2a594cef34d2e9109bad847358d57ac4615f81f4
        #     │   └── pex-2.0.2-py2.py3-none-any.whl
        #     │       ├── bin
        #     │       ├── pex
        #     │       └── pex-2.0.2.dist-info
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
        # When the pex is run, the runtime key is followed to the build time key, avoiding re-unpacking
        # the wheel:
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
        wheel_dir_hash = CacheHelper.dir_hash(self.install_chroot)
        runtime_key_dir = os.path.join(self.installation_root, wheel_dir_hash)
        with atomic_directory(runtime_key_dir, exclusive=False) as work_dir:
            if work_dir:
                # Note: Create a relative path symlink between the two directories so that the PEX_ROOT
                # can be used within a chroot environment where the prefix of the path may change
                # between programs running inside and outside of the chroot.
                source_path = os.path.join(work_dir, self.request.wheel_file)
                start_dir = os.path.dirname(source_path)
                relative_target_path = os.path.relpath(self.install_chroot, start_dir)
                os.symlink(relative_target_path, source_path)

        return self._iter_requirements_requests(install_requests)

    def _iter_requirements_requests(self, install_requests):
        if self.is_installed:
            # N.B.: Direct snip from the Environment docs:
            #
            #  You may explicitly set `platform` (and/or `python`) to ``None`` if you
            #  wish to map *all* distributions, not just those compatible with the
            #  running platform or Python version.
            #
            # Since our requested target may be foreign, we make sure find all distributions installed by
            # explicitly setting both `python` and `platform` to `None`.
            environment = Environment(search_path=[self.install_chroot], python=None, platform=None)

            distributions = []
            for dist_project_name in environment:
                distributions.extend(environment[dist_project_name])

            for install_request in install_requests:
                yield DistributionRequirements.Request(
                    target=install_request.target, distributions=distributions
                )


class BuildAndInstallRequest(object):
    def __init__(
        self,
        build_requests,
        install_requests,
        package_index_configuration=None,
        cache=None,
        compile=False,
    ):

        self._build_requests = build_requests
        self._install_requests = install_requests
        self._package_index_configuration = package_index_configuration
        self._cache = cache
        self._compile = compile

    def _categorize_build_requests(self, build_requests, dist_root):
        unsatisfied_build_requests = []
        install_requests = []
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
                install_requests.extend(build_result.finalize_build())
        return unsatisfied_build_requests, install_requests

    def _spawn_wheel_build(self, built_wheels_dir, build_request):
        build_result = build_request.result(built_wheels_dir)
        build_job = get_pip().spawn_build_wheels(
            distributions=[build_request.source_path],
            wheel_dir=build_result.build_dir,
            cache=self._cache,
            package_index_configuration=self._package_index_configuration,
            interpreter=build_request.target.get_interpreter(),
        )
        return SpawnedJob.wait(job=build_job, result=build_result)

    def _categorize_install_requests(self, install_requests, installed_wheels_dir):
        unsatisfied_install_requests = []
        install_results = []
        for install_request in install_requests:
            install_result = install_request.result(installed_wheels_dir)
            if not install_result.is_installed:
                TRACER.log(
                    "Installing {} in {}".format(
                        install_request.wheel_path, install_result.install_chroot
                    )
                )
                unsatisfied_install_requests.append(install_request)
            else:
                TRACER.log(
                    "Using cached installation of {} at {}".format(
                        install_request.wheel_file, install_result.install_chroot
                    )
                )
                install_results.append(install_result)
        return unsatisfied_install_requests, install_results

    def _spawn_install(self, installed_wheels_dir, install_request):
        install_result = install_request.result(installed_wheels_dir)
        install_job = get_pip().spawn_install_wheel(
            wheel=install_request.wheel_path,
            install_dir=install_result.build_chroot,
            compile=self._compile,
            cache=self._cache,
            target=install_request.target,
        )
        return SpawnedJob.wait(job=install_job, result=install_result)

    def install_distributions(self, ignore_errors=False, workspace=None, max_parallel_jobs=None):
        if not any((self._build_requests, self._install_requests)):
            # Nothing to build or install.
            return []

        cache = self._cache or workspace or safe_mkdtemp()

        built_wheels_dir = os.path.join(cache, "built_wheels")
        spawn_wheel_build = functools.partial(self._spawn_wheel_build, built_wheels_dir)

        installed_wheels_dir = os.path.join(cache, PexInfo.INSTALL_CACHE)
        spawn_install = functools.partial(self._spawn_install, installed_wheels_dir)

        to_install = self._install_requests[:]
        to_calculate_requirements_for = []

        # 1. Build local projects and sdists.
        if self._build_requests:
            with TRACER.timed(
                "Building distributions for:"
                "\n  {}".format("\n  ".join(map(str, self._build_requests)))
            ):

                build_requests, install_requests = self._categorize_build_requests(
                    build_requests=self._build_requests, dist_root=built_wheels_dir
                )
                to_install.extend(install_requests)

                for build_result in execute_parallel(
                    inputs=build_requests,
                    spawn_func=spawn_wheel_build,
                    error_handler=Raise(Untranslatable),
                    max_jobs=max_parallel_jobs,
                ):
                    to_install.extend(build_result.finalize_build())

        # 2. Install wheels in individual chroots.

        # Dedup by wheel name; e.g.: only install universal wheels once even though they'll get
        # downloaded / built for each interpreter or platform.
        install_requests_by_wheel_file = OrderedDict()
        for install_request in to_install:
            install_requests = install_requests_by_wheel_file.setdefault(
                install_request.wheel_file, []
            )
            install_requests.append(install_request)

        representative_install_requests = [
            requests[0] for requests in install_requests_by_wheel_file.values()
        ]

        def add_requirements_requests(install_result):
            install_requests = install_requests_by_wheel_file[install_result.request.wheel_file]
            to_calculate_requirements_for.extend(install_result.finalize_install(install_requests))

        with TRACER.timed(
            "Installing:" "\n  {}".format("\n  ".join(map(str, representative_install_requests)))
        ):

            install_requests, install_results = self._categorize_install_requests(
                install_requests=representative_install_requests,
                installed_wheels_dir=installed_wheels_dir,
            )
            for install_result in install_results:
                add_requirements_requests(install_result)

            for install_result in execute_parallel(
                inputs=install_requests,
                spawn_func=spawn_install,
                error_handler=Raise(Untranslatable),
                max_jobs=max_parallel_jobs,
            ):
                add_requirements_requests(install_result)

        # 3. Calculate the final installed requirements.
        with TRACER.timed(
            "Calculating installed requirements for:"
            "\n  {}".format("\n  ".join(map(str, to_calculate_requirements_for)))
        ):
            distribution_requirements = DistributionRequirements.merged(
                execute_parallel(
                    inputs=to_calculate_requirements_for,
                    spawn_func=DistributionRequirements.Request.spawn_calculation,
                    error_handler=Raise(Untranslatable),
                    max_jobs=max_parallel_jobs,
                )
            )

        installed_distributions = OrderedSet()
        for requirements_request in to_calculate_requirements_for:
            for distribution in requirements_request.distributions:
                installed_distributions.add(
                    InstalledDistribution(
                        target=requirements_request.target,
                        requirement=distribution_requirements.to_requirement(distribution),
                        distribution=distribution,
                    )
                )

        if not ignore_errors:
            self._check_install(installed_distributions)
        return installed_distributions

    def _check_install(self, installed_distributions):
        installed_distribution_by_key = OrderedDict(
            (resolved_distribution.requirement.key, resolved_distribution)
            for resolved_distribution in installed_distributions
        )

        unsatisfied = []
        for installed_distribution in installed_distribution_by_key.values():
            dist = installed_distribution.distribution
            target = installed_distribution.target
            for requirement in dist.requires():
                if not target.requirement_applies(requirement):
                    continue

                installed_requirement_dist = installed_distribution_by_key.get(requirement.key)
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


def resolve(
    requirements=None,
    requirement_files=None,
    constraint_files=None,
    allow_prereleases=False,
    transitive=True,
    interpreter=None,
    platform=None,
    indexes=None,
    find_links=None,
    network_configuration=None,
    cache=None,
    build=True,
    use_wheel=True,
    compile=False,
    manylinux=None,
    max_parallel_jobs=None,
    ignore_errors=False,
):
    """Produce all distributions needed to meet all specified requirements.

    :keyword requirements: A sequence of requirement strings.
    :type requirements: list of str
    :keyword requirement_files: A sequence of requirement file paths.
    :type requirement_files: list of str
    :keyword constraint_files: A sequence of constraint file paths.
    :type constraint_files: list of str
    :keyword bool allow_prereleases: Whether to include pre-release and development versions when
      resolving requirements. Defaults to ``False``, but any requirements that explicitly request
      prerelease or development versions will override this setting.
    :keyword bool transitive: Whether to resolve transitive dependencies of requirements.
      Defaults to ``True``.
    :keyword interpreter: If specified, distributions will be resolved for this interpreter, and
      non-wheel distributions will be built against this interpreter. If both `interpreter` and
      `platform` are ``None`` (the default), this defaults to the current interpreter.
    :type interpreter: :class:`pex.interpreter.PythonInterpreter`
    :keyword str platform: The exact PEP425-compatible platform string to resolve distributions for,
      in addition to the platform of the given interpreter, if provided. If any distributions need
      to be built, use the interpreter argument instead, providing the corresponding interpreter.
      However, if the platform matches the current interpreter, the current interpreter will be used
      to build any non-wheels.
    :keyword indexes: A list of urls or paths pointing to PEP 503 compliant repositories to search for
      distributions. Defaults to ``None`` which indicates to use the default pypi index. To turn off
      use of all indexes, pass an empty list.
    :type indexes: list of str
    :keyword find_links: A list or URLs, paths to local html files or directory paths. If URLs or
      local html file paths, these are parsed for links to distributions. If a local directory path,
      its listing is used to discover distributions.
    :type find_links: list of str
    :keyword network_configuration: Configuration for network requests made downloading and building
      distributions.
    :type network_configuration: :class:`pex.network_configuration.NetworkConfiguration`
    :keyword str cache: A directory path to use to cache distributions locally.
    :keyword bool build: Whether to allow building source distributions when no wheel is found.
      Defaults to ``True``.
    :keyword bool use_wheel: Whether to allow resolution of pre-built wheel distributions.
      Defaults to ``True``.
    :keyword bool compile: Whether to pre-compile resolved distribution python sources.
      Defaults to ``False``.
    :keyword str manylinux: The upper bound manylinux standard to support when targeting foreign linux
      platforms. Defaults to ``None``.
    :keyword int max_parallel_jobs: The maximum number of parallel jobs to use when resolving,
      building and installing distributions in a resolve. Defaults to the number of CPUs available.
    :keyword bool ignore_errors: Whether to ignore resolution solver errors. Defaults to ``False``.
    :returns: List of :class:`ResolvedDistribution` instances meeting ``requirements``.
    :raises Unsatisfiable: If ``requirements`` is not transitively satisfiable.
    :raises Untranslatable: If no compatible distributions could be acquired for
      a particular requirement.
    :raises ValueError: If a foreign `platform` was provided, and `use_wheel=False`.
    :raises ValueError: If `build=False` and `use_wheel=False`.
    """
    # TODO(https://github.com/pantsbuild/pex/issues/969): Deprecate resolve with a single interpreter
    #  or platform and rename resolve_multi to resolve for a single API entrypoint to a full resolve.
    return resolve_multi(
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
        allow_prereleases=allow_prereleases,
        transitive=transitive,
        interpreters=None if interpreter is None else [interpreter],
        platforms=None if platform is None else [platform],
        indexes=indexes,
        find_links=find_links,
        network_configuration=network_configuration,
        cache=cache,
        build=build,
        use_wheel=use_wheel,
        compile=compile,
        manylinux=manylinux,
        max_parallel_jobs=max_parallel_jobs,
        ignore_errors=ignore_errors,
    )


def resolve_multi(
    requirements=None,
    requirement_files=None,
    constraint_files=None,
    allow_prereleases=False,
    transitive=True,
    interpreters=None,
    platforms=None,
    indexes=None,
    find_links=None,
    network_configuration=None,
    cache=None,
    build=True,
    use_wheel=True,
    compile=False,
    manylinux=None,
    max_parallel_jobs=None,
    ignore_errors=False,
):
    """Resolves all distributions needed to meet requirements for multiple distribution targets.

    The resulting distributions are installed in individual chroots that can be independently added
    to `sys.path`

    :keyword requirements: A sequence of requirement strings.
    :type requirements: list of str
    :keyword requirement_files: A sequence of requirement file paths.
    :type requirement_files: list of str
    :keyword constraint_files: A sequence of constraint file paths.
    :type constraint_files: list of str
    :keyword bool allow_prereleases: Whether to include pre-release and development versions when
      resolving requirements. Defaults to ``False``, but any requirements that explicitly request
      prerelease or development versions will override this setting.
    :keyword bool transitive: Whether to resolve transitive dependencies of requirements.
      Defaults to ``True``.
    :keyword interpreters: If specified, distributions will be resolved for these interpreters, and
      non-wheel distributions will be built against each interpreter. If both `interpreters` and
      `platforms` are ``None`` (the default) or an empty iterable, this defaults to a list
      containing only the current interpreter.
    :type interpreters: list of :class:`pex.interpreter.PythonInterpreter`
    :keyword platforms: An iterable of PEP425-compatible platform strings to resolve distributions
      for, in addition to the platforms of any given interpreters. If any distributions need to be
      built, use the interpreters argument instead, providing the corresponding interpreter.
      However, if any platform matches the current interpreter, the current interpreter will be used
      to build any non-wheels for that platform.
    :type platforms: list of str
    :keyword indexes: A list of urls or paths pointing to PEP 503 compliant repositories to search for
      distributions. Defaults to ``None`` which indicates to use the default pypi index. To turn off
      use of all indexes, pass an empty list.
    :type indexes: list of str
    :keyword find_links: A list or URLs, paths to local html files or directory paths. If URLs or
      local html file paths, these are parsed for links to distributions. If a local directory path,
      its listing is used to discover distributions.
    :type find_links: list of str
    :keyword network_configuration: Configuration for network requests made downloading and building
      distributions.
    :type network_configuration: :class:`pex.network_configuration.NetworkConfiguration`
    :keyword str cache: A directory path to use to cache distributions locally.
    :keyword bool build: Whether to allow building source distributions when no wheel is found.
      Defaults to ``True``.
    :keyword bool use_wheel: Whether to allow resolution of pre-built wheel distributions.
      Defaults to ``True``.
    :keyword bool compile: Whether to pre-compile resolved distribution python sources.
      Defaults to ``False``.
    :keyword str manylinux: The upper bound manylinux standard to support when targeting foreign linux
      platforms. Defaults to ``None``.
    :keyword int max_parallel_jobs: The maximum number of parallel jobs to use when resolving,
      building and installing distributions in a resolve. Defaults to the number of CPUs available.
    :keyword bool ignore_errors: Whether to ignore resolution solver errors. Defaults to ``False``.
    :returns: List of :class:`ResolvedDistribution` instances meeting ``requirements``.
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

    workspace = safe_mkdtemp()

    package_index_configuration = PackageIndexConfiguration.create(
        indexes=indexes, find_links=find_links, network_configuration=network_configuration
    )
    build_requests, download_results = _download_internal(
        interpreters=interpreters,
        platforms=platforms,
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
        allow_prereleases=allow_prereleases,
        transitive=transitive,
        package_index_configuration=package_index_configuration,
        cache=cache,
        build=build,
        use_wheel=use_wheel,
        manylinux=manylinux,
        dest=workspace,
        max_parallel_jobs=max_parallel_jobs,
    )

    install_requests = []
    if download_results is not None:
        for download_result in download_results:
            build_requests.extend(download_result.build_requests())
            install_requests.extend(download_result.install_requests())

    build_and_install_request = BuildAndInstallRequest(
        build_requests=build_requests,
        install_requests=install_requests,
        package_index_configuration=package_index_configuration,
        cache=cache,
        compile=compile,
    )

    ignore_errors = ignore_errors or not transitive
    return list(
        build_and_install_request.install_distributions(
            ignore_errors=ignore_errors, workspace=workspace, max_parallel_jobs=max_parallel_jobs
        )
    )


def _download_internal(
    requirements=None,
    requirement_files=None,
    constraint_files=None,
    allow_prereleases=False,
    transitive=True,
    interpreters=None,
    platforms=None,
    package_index_configuration=None,
    cache=None,
    build=True,
    use_wheel=True,
    manylinux=None,
    dest=None,
    max_parallel_jobs=None,
):

    parsed_platforms = [parsed_platform(platform) for platform in platforms] if platforms else []

    def iter_targets():
        if not interpreters and not parsed_platforms:
            # No specified targets, so just build for the current interpreter (on the current platform).
            yield DistributionTarget.current()
            return

        if interpreters:
            for interpreter in interpreters:
                # Build for the specified local interpreters (on the current platform).
                yield DistributionTarget.for_interpreter(interpreter)

        if parsed_platforms:
            for platform in parsed_platforms:
                if platform is not None or not interpreters:
                    # 1. Build for specific platforms.
                    # 2. Build for the current platform (None) only if not done already (ie: no intepreters
                    #    were specified).
                    yield DistributionTarget.for_platform(platform)

    # Only download for each target once. The download code assumes this unique targets optimization
    # when spawning parallel downloads.
    # TODO(John Sirois): centralize the de-deuping in the DownloadRequest constructor when we drop
    # python 2.7 and move from namedtuples to dataclasses.
    unique_targets = OrderedSet(iter_targets())
    download_request = DownloadRequest(
        targets=unique_targets,
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
        allow_prereleases=allow_prereleases,
        transitive=transitive,
        package_index_configuration=package_index_configuration,
        cache=cache,
        build=build,
        use_wheel=use_wheel,
        manylinux=manylinux,
    )

    local_projects = list(download_request.iter_local_projects())

    dest = dest or safe_mkdtemp()
    download_results = download_request.download_distributions(
        dest=dest, max_parallel_jobs=max_parallel_jobs
    )
    return local_projects, download_results


class LocalDistribution(namedtuple("LocalDistribution", ["target", "path", "fingerprint"])):
    @classmethod
    def create(cls, path, fingerprint=None, target=None):
        fingerprint = fingerprint or fingerprint_path(path)
        target = target or DistributionTarget.current()
        return cls(target=target, path=path, fingerprint=fingerprint)

    @property
    def is_wheel(self):
        return self.path.endswith(".whl") and zipfile.is_zipfile(self.path)


def download(
    requirements=None,
    requirement_files=None,
    constraint_files=None,
    allow_prereleases=False,
    transitive=True,
    interpreters=None,
    platforms=None,
    indexes=None,
    find_links=None,
    network_configuration=None,
    cache=None,
    build=True,
    use_wheel=True,
    manylinux=None,
    dest=None,
    max_parallel_jobs=None,
):
    """Downloads all distributions needed to meet requirements for multiple distribution targets.

    :keyword requirements: A sequence of requirement strings.
    :type requirements: list of str
    :keyword requirement_files: A sequence of requirement file paths.
    :type requirement_files: list of str
    :keyword constraint_files: A sequence of constraint file paths.
    :type constraint_files: list of str
    :keyword bool allow_prereleases: Whether to include pre-release and development versions when
      resolving requirements. Defaults to ``False``, but any requirements that explicitly request
      prerelease or development versions will override this setting.
    :keyword bool transitive: Whether to resolve transitive dependencies of requirements.
      Defaults to ``True``.
    :keyword interpreters: If specified, distributions will be resolved for these interpreters.
      If both `interpreters` and `platforms` are ``None`` (the default) or an empty iterable, this
      defaults to a list containing only the current interpreter.
    :type interpreters: list of :class:`pex.interpreter.PythonInterpreter`
    :keyword platforms: An iterable of PEP425-compatible platform strings to resolve distributions
      for, in addition to the platforms of any given interpreters.
    :type platforms: list of str
    :keyword indexes: A list of urls or paths pointing to PEP 503 compliant repositories to search for
      distributions. Defaults to ``None`` which indicates to use the default pypi index. To turn off
      use of all indexes, pass an empty list.
    :type indexes: list of str
    :keyword find_links: A list or URLs, paths to local html files or directory paths. If URLs or
      local html file paths, these are parsed for links to distributions. If a local directory path,
      its listing is used to discover distributions.
    :type find_links: list of str
    :keyword network_configuration: Configuration for network requests made downloading and building
      distributions.
    :type network_configuration: :class:`pex.network_configuration.NetworkConfiguration`
    :keyword str cache: A directory path to use to cache distributions locally.
    :keyword bool build: Whether to allow building source distributions when no wheel is found.
      Defaults to ``True``.
    :keyword bool use_wheel: Whether to allow resolution of pre-built wheel distributions.
      Defaults to ``True``.
    :keyword str manylinux: The upper bound manylinux standard to support when targeting foreign linux
      platforms. Defaults to ``None``.
    :keyword str dest: A directory path to download distributions to.
    :keyword int max_parallel_jobs: The maximum number of parallel jobs to use when resolving,
      building and installing distributions in a resolve. Defaults to the number of CPUs available.
    :returns: List of :class:`LocalDistribution` instances meeting ``requirements``.
    :raises Unsatisfiable: If the resolution of download of distributions fails for any reason.
    :raises ValueError: If a foreign platform was provided in `platforms`, and `use_wheel=False`.
    :raises ValueError: If `build=False` and `use_wheel=False`.
    """

    package_index_configuration = PackageIndexConfiguration.create(
        indexes=indexes, find_links=find_links, network_configuration=network_configuration
    )
    local_distributions, download_results = _download_internal(
        interpreters=interpreters,
        platforms=platforms,
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
        allow_prereleases=allow_prereleases,
        transitive=transitive,
        package_index_configuration=package_index_configuration,
        cache=cache,
        build=build,
        use_wheel=use_wheel,
        manylinux=manylinux,
        dest=dest,
        max_parallel_jobs=max_parallel_jobs,
    )

    for download_result in download_results:
        for build_request in download_result.build_requests():
            local_distributions.append(
                LocalDistribution(
                    target=build_request.target,
                    path=build_request.source_path,
                    fingerprint=build_request.fingerprint,
                )
            )
        for install_request in download_result.install_requests():
            local_distributions.append(
                LocalDistribution(
                    target=install_request.target,
                    path=install_request.wheel_path,
                    fingerprint=install_request.fingerprint,
                )
            )

    return local_distributions


def install(
    local_distributions,
    indexes=None,
    find_links=None,
    network_configuration=None,
    cache=None,
    compile=False,
    max_parallel_jobs=None,
    ignore_errors=False,
):
    """Installs distributions in individual chroots that can be independently added to `sys.path`.

    :keyword local_distributions: The local distributions to install.
    :type local_distributions: list of :class:`LocalDistribution`
    :keyword indexes: A list of urls or paths pointing to PEP 503 compliant repositories to search for
      distributions. Defaults to ``None`` which indicates to use the default pypi index. To turn off
      use of all indexes, pass an empty list.
    :type indexes: list of str
    :keyword find_links: A list or URLs, paths to local html files or directory paths. If URLs or
      local html file paths, these are parsed for links to distributions. If a local directory path,
      its listing is used to discover distributions.
    :type find_links: list of str
    :keyword network_configuration: Configuration for network requests made downloading and building
      distributions.
    :type network_configuration: :class:`pex.network_configuration.NetworkConfiguration`
    :keyword str cache: A directory path to use to cache distributions locally.
    :keyword bool compile: Whether to pre-compile resolved distribution python sources.
      Defaults to ``False``.
    :keyword int max_parallel_jobs: The maximum number of parallel jobs to use when resolving,
      building and installing distributions in a resolve. Defaults to the number of CPUs available.
    :keyword bool ignore_errors: Whether to ignore resolution solver errors. Defaults to ``False``.
    :returns: List of :class:`InstalledDistribution` instances meeting ``requirements``.
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
        indexes=indexes, find_links=find_links, network_configuration=network_configuration
    )
    build_and_install_request = BuildAndInstallRequest(
        build_requests=build_requests,
        install_requests=install_requests,
        package_index_configuration=package_index_configuration,
        cache=cache,
        compile=compile,
    )

    return list(
        build_and_install_request.install_distributions(
            ignore_errors=ignore_errors, max_parallel_jobs=max_parallel_jobs
        )
    )
