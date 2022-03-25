# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import json
import os
import pkgutil
import re
import subprocess
import sys
from abc import abstractmethod
from collections import defaultdict, deque

from pex import dist_metadata, targets, third_party
from pex.common import atomic_directory, safe_mkdtemp
from pex.compatibility import urlparse
from pex.dist_metadata import ProjectNameAndVersion
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import iter_compatible_versions
from pex.jobs import Job
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pep_376 import Record
from pex.pep_425 import CompatibilityTags
from pex.pex import PEX
from pex.pex_bootstrapper import ensure_venv
from pex.pip.vcs import fingerprint_downloaded_vcs_archive
from pex.platforms import Platform
from pex.requirements import VCS, VCSScheme, parse_scheme
from pex.resolve.locked_resolve import LockRequest, LockStyle
from pex.resolve.resolved_requirement import Fingerprint, PartialArtifact, Pin, ResolvedRequirement
from pex.resolve.resolver_configuration import ResolverVersion
from pex.targets import AbbreviatedPlatform, CompletePlatform, LocalInterpreter, Target
from pex.third_party import isolated
from pex.third_party.pkg_resources import Requirement
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, Generic
from pex.util import named_temporary_file
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import (
        Any,
        Callable,
        DefaultDict,
        Dict,
        Iterable,
        Iterator,
        List,
        Mapping,
        Optional,
        Pattern,
        Protocol,
        Sequence,
        Set,
        Tuple,
        TypeVar,
        Union,
    )

    import attr  # vendor:skip

    class CSVWriter(Protocol):
        def writerow(self, row):
            # type: (Iterable[Union[str, int]]) -> None
            pass

else:
    from pex.third_party import attr


class PackageIndexConfiguration(object):
    @staticmethod
    def _calculate_args(
        indexes=None,  # type: Optional[Sequence[str]]
        find_links=None,  # type: Optional[Iterable[str]]
        network_configuration=None,  # type: Optional[NetworkConfiguration]
    ):
        # type: (...) -> Iterator[str]

        # N.B.: `--cert` and `--client-cert` are passed via env var to work around:
        #   https://github.com/pypa/pip/issues/5502
        # See `_calculate_env`.

        trusted_hosts = []

        def maybe_trust_insecure_host(url):
            url_info = urlparse.urlparse(url)
            if "http" == url_info.scheme:
                # Implicitly trust explicitly asked for http indexes and find_links repos instead of
                # requiring separate trust configuration.
                trusted_hosts.append(url_info.netloc)
            return url

        # N.B.: We interpret None to mean accept pip index defaults, [] to mean turn off all index
        # use.
        if indexes is not None:
            if len(indexes) == 0:
                yield "--no-index"
            else:
                all_indexes = deque(indexes)
                yield "--index-url"
                yield maybe_trust_insecure_host(all_indexes.popleft())
                if all_indexes:
                    for extra_index in all_indexes:
                        yield "--extra-index-url"
                        yield maybe_trust_insecure_host(extra_index)

        if find_links:
            for find_link_url in find_links:
                yield "--find-links"
                yield maybe_trust_insecure_host(find_link_url)

        for trusted_host in trusted_hosts:
            yield "--trusted-host"
            yield trusted_host

        network_configuration = network_configuration or NetworkConfiguration()

        yield "--retries"
        yield str(network_configuration.retries)

        yield "--timeout"
        yield str(network_configuration.timeout)

    @staticmethod
    def _calculate_env(
        network_configuration,  # type: NetworkConfiguration
        isolated,  # type: bool
    ):
        # type: (...) -> Iterator[Tuple[str, str]]
        if network_configuration.proxy:
            # We use the backdoor of the universality of http(s)_proxy env var support to continue
            # to allow Pip to operate in `--isolated` mode.
            yield "http_proxy", network_configuration.proxy
            yield "https_proxy", network_configuration.proxy

        if network_configuration.cert:
            # We use the backdoor of requests (which is vendored by Pip to handle all network
            # operations) support for REQUESTS_CA_BUNDLE when possible to continue to allow Pip to
            # operate in `--isolated` mode.
            yield (
                ("REQUESTS_CA_BUNDLE" if isolated else "PIP_CERT"),
                os.path.abspath(network_configuration.cert),
            )

        if network_configuration.client_cert:
            assert not isolated
            yield "PIP_CLIENT_CERT", os.path.abspath(network_configuration.client_cert)

    @classmethod
    def create(
        cls,
        resolver_version=None,  # type: Optional[ResolverVersion.Value]
        indexes=None,  # type: Optional[Sequence[str]]
        find_links=None,  # type: Optional[Iterable[str]]
        network_configuration=None,  # type: Optional[NetworkConfiguration]
    ):
        # type: (...) -> PackageIndexConfiguration
        resolver_version = resolver_version or ResolverVersion.PIP_LEGACY
        network_configuration = network_configuration or NetworkConfiguration()

        # We must pass `--client-cert` via PIP_CLIENT_CERT to work around
        # https://github.com/pypa/pip/issues/5502. We can only do this by breaking Pip `--isolated`
        # mode.
        isolated = not network_configuration.client_cert

        return cls(
            resolver_version=resolver_version,
            network_configuration=network_configuration,
            args=cls._calculate_args(
                indexes=indexes, find_links=find_links, network_configuration=network_configuration
            ),
            env=cls._calculate_env(network_configuration=network_configuration, isolated=isolated),
            isolated=isolated,
        )

    def __init__(
        self,
        resolver_version,  # type: ResolverVersion.Value
        network_configuration,  # type: NetworkConfiguration
        args,  # type: Iterable[str]
        env,  # type: Iterable[Tuple[str, str]]
        isolated,  # type: bool
    ):
        # type: (...) -> None
        self.resolver_version = resolver_version  # type: ResolverVersion.Value
        self.network_configuration = network_configuration  # type: NetworkConfiguration
        self.args = tuple(args)  # type: Iterable[str]
        self.env = dict(env)  # type: Mapping[str, str]
        self.isolated = isolated  # type: bool


if TYPE_CHECKING:
    _T = TypeVar("_T")


class _LogAnalyzer(object):
    class Complete(Generic["_T"]):
        def __init__(self, data=None):
            # type: (Optional[_T]) -> None
            self.data = data

    class Continue(Generic["_T"]):
        def __init__(self, data=None):
            # type: (Optional[_T]) -> None
            self.data = data

    @abstractmethod
    def should_collect(self, returncode):
        # type: (int) -> bool
        """"""

    @abstractmethod
    def analyze(self, line):
        # type: (str) -> Union[Complete, Continue]
        """Analyze the given log line.

        Returns a value indicating whether or not analysis is complete.
        """

    def analysis_completed(self):
        # type: () -> None
        """Called to indicate the log analysis is complete."""


class ErrorMessage(str):
    pass


if TYPE_CHECKING:
    ErrorAnalysis = Union[_LogAnalyzer.Complete[ErrorMessage], _LogAnalyzer.Continue[ErrorMessage]]


class _ErrorAnalyzer(_LogAnalyzer):
    def should_collect(self, returncode):
        # type: (int) -> bool
        return returncode != 0

    @abstractmethod
    def analyze(self, line):
        # type: (str) -> ErrorAnalysis
        """Analyze the given log line.

        Returns a value indicating whether or not analysis is complete.
        """


@attr.s
class _Issue9420Analyzer(_ErrorAnalyzer):
    # Works around: https://github.com/pypa/pip/issues/9420

    _strip = attr.ib(default=None)  # type: Optional[int]

    def analyze(self, line):
        # type: (str) -> ErrorAnalysis
        # N.B.: Pip --log output looks like:
        # 2021-01-04T16:12:01,119 ERROR: Cannot install pantsbuild-pants==1.24.0.dev2 and wheel==0.33.6 because these package versions have conflicting dependencies.
        # 2021-01-04T16:12:01,119
        # 2021-01-04T16:12:01,119 The conflict is caused by:
        # 2021-01-04T16:12:01,119     The user requested wheel==0.33.6
        # 2021-01-04T16:12:01,119     pantsbuild-pants 1.24.0.dev2 depends on wheel==0.31.1
        # 2021-01-04T16:12:01,119
        # 2021-01-04T16:12:01,119 To fix this you could try to:
        # 2021-01-04T16:12:01,119 1. loosen the range of package versions you've specified
        # 2021-01-04T16:12:01,119 2. remove package versions to allow pip attempt to solve the dependency conflict
        # 2021-01-04T16:12:01,119 ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/en/latest/user_guide/#fixing-conflicting-dependencies
        if not self._strip:
            match = re.match(r"^(?P<timestamp>[^ ]+) ERROR: Cannot install ", line)
            if match:
                self._strip = len(match.group("timestamp"))
        else:
            match = re.match(r"^[^ ]+ ERROR: ResolutionImpossible: ", line)
            if match:
                return self.Complete()
            else:
                return self.Continue(ErrorMessage(line[self._strip :]))
        return self.Continue()


@attr.s(frozen=True)
class _Issue10050Analyzer(_ErrorAnalyzer):
    # Part of the workaround for: https://github.com/pypa/pip/issues/10050

    _platform = attr.ib()  # type: Platform

    def analyze(self, line):
        # type: (str) -> ErrorAnalysis
        # N.B.: Pip --log output looks like:
        # 2021-06-20T19:06:00,981 pip._vendor.packaging.markers.UndefinedEnvironmentName: 'python_full_version' does not exist in evaluation environment.
        match = re.match(
            r"^[^ ]+ pip._vendor.packaging.markers.UndefinedEnvironmentName: "
            r"(?P<missing_marker>.*)\.$",
            line,
        )
        if match:
            return self.Complete(
                ErrorMessage(
                    "Failed to resolve for platform {}. Resolve requires evaluation of unknown "
                    "environment marker: {}.".format(self._platform, match.group("missing_marker"))
                )
            )
        return self.Continue()


@attr.s(frozen=True)
class _VCSPartialInfo(object):
    vcs = attr.ib()  # type: VCS.Value
    via = attr.ib()  # type: Tuple[str, ...]


class Locker(_LogAnalyzer):
    def __init__(
        self,
        lock_request,  # type: LockRequest
        download_dir,  # type: str
    ):
        # type: (...) -> None
        self._lock_request = lock_request
        self._download_dir = download_dir

        self._saved_re = re.compile(
            r"Saved (?:{download_dir}){dir_sep}(?P<filename>.+)$".format(
                download_dir="|".join(
                    re.escape(path)
                    for path in frozenset(
                        (self._download_dir, os.path.realpath(self._download_dir))
                    )
                ),
                dir_sep=re.escape(os.path.sep),
            )
        )
        self._saved = set()  # type: Set[Pin]

        self._resolved_requirements = []  # type: List[ResolvedRequirement]
        self._links = defaultdict(OrderedSet)  # type: DefaultDict[Pin, OrderedSet[PartialArtifact]]
        self._done_building_re = None  # type: Optional[Pattern]
        self._vcs_partial_info = None  # type: Optional[_VCSPartialInfo]

    @property
    def style(self):
        # type: () -> LockStyle.Value
        return self._lock_request.lock_configuration.style

    @property
    def requires_python(self):
        # type: () -> Tuple[str, ...]
        return self._lock_request.lock_configuration.requires_python

    def should_collect(self, returncode):
        # type: (int) -> bool
        return returncode == 0

    @staticmethod
    def _extract_resolve_data(url):
        # type: (str) -> Tuple[Pin, PartialArtifact]

        fingerprint = None  # type: Optional[Fingerprint]
        fingerprint_match = re.search(r"(?P<url>[^#]+)#(?P<algorithm>[^=]+)=(?P<hash>.*)$", url)
        if fingerprint_match:
            url = fingerprint_match.group("url")
            algorithm = fingerprint_match.group("algorithm")
            hash_ = fingerprint_match.group("hash")
            fingerprint = Fingerprint(algorithm=algorithm, hash=hash_)

        pin = Pin.canonicalize(ProjectNameAndVersion.from_filename(urlparse.urlparse(url).path))
        partial_artifact = PartialArtifact(url, fingerprint)
        return pin, partial_artifact

    def analyze(self, line):
        # type: (str) -> _LogAnalyzer.Continue[None]

        # The log sequence for processing a resolved requirement is as follows (log lines irrelevant
        # to our purposes omitted):
        #
        #   1.) "... Found link <url1> ..."
        #   ...
        #   1.) "... Found link <urlN> ..."
        #   2.) "... Added <requirement> from <url> ... to build tracker ..."
        #   3.) Lines related to extracting metadata from <requirement>'s artifact
        # * 4.) "... Source in <tmp> has version <version>, which satisfies requirement "
        #       "<requirement> from <url> ..."
        #   5.) "... Removed <requirement> from <url> ... from build tracker ..."
        #   6.) "... Saved <download dir>/<artifact file>

        # The lines in section 3 can contain this same pattern of lines if the metadata extraction
        # proceeds via PEP-517 which recursively uses Pip to resolve build dependencies. We want to
        # ignore this recursion since a lock should only contain install requirements and not build
        # requirements (If a build proceeds differently tomorrow than today then we don't care as
        # long as the final built artifact hashes the same. In other words, we completely rely on a
        # cryptographic fingerprint for reproducibility and security guarantees from a lock).

        # The section 4 line will be present for requirements that represent either local source
        # directories or VCS requirements and can be used to learn their version.

        if self._done_building_re:
            if self._done_building_re.search(line):
                self._done_building_re = None
            elif self._vcs_partial_info is not None:
                match = re.search(
                    r"Source in .+ has version (?P<version>[^\s]+), which satisfies requirement "
                    r"(?P<requirement>.+) from (?P<url>[^\s]+)(?: \(from .+)?$",
                    line,
                )
                if match:
                    vcs_partial_info = self._vcs_partial_info
                    self._vcs_partial_info = None

                    raw_requirement = match.group("requirement")
                    requirement = Requirement.parse(raw_requirement)
                    project_name = requirement.project_name
                    version = match.group("version")

                    # VCS requirements are satisfied by a singular source; so we need not consult
                    # links collected in this round.
                    self._links.clear()

                    self._resolved_requirements.append(
                        ResolvedRequirement(
                            requirement=requirement,
                            pin=Pin.canonicalize(ProjectNameAndVersion(project_name, version)),
                            artifact=PartialArtifact(
                                url=match.group("url"),
                                fingerprint=fingerprint_downloaded_vcs_archive(
                                    download_dir=self._download_dir,
                                    project_name=project_name,
                                    version=version,
                                    vcs=vcs_partial_info.vcs,
                                ),
                                verified=True,
                            ),
                            via=vcs_partial_info.via,
                        )
                    )
            return self.Continue()

        match = re.search(
            r"Added (?P<requirement>.+) from (?P<url>[^\s]+) (?:\(from (?P<from>.*)\) )?to build "
            r"tracker",
            line,
        )
        if match:
            raw_requirement = match.group("requirement")
            url = match.group("url")
            self._done_building_re = re.compile(
                r"Removed {requirement} from {url} (?:.* )?from build tracker".format(
                    requirement=re.escape(raw_requirement), url=re.escape(url)
                )
            )

            from_ = match.group("from")
            if from_:
                via = tuple(from_.split("->"))
            else:
                via = ()

            parsed_scheme = parse_scheme(urlparse.urlparse(url).scheme)
            if isinstance(parsed_scheme, VCSScheme):
                # We'll get the remaining information we need to record the resolved VCS requirement
                # in a later log line; so just save what we have so far.
                self._vcs_partial_info = _VCSPartialInfo(vcs=parsed_scheme.vcs, via=via)
            else:
                requirement = Requirement.parse(raw_requirement)
                project_name_and_version, partial_artifact = self._extract_resolve_data(url)

                additional_artifacts = self._links[project_name_and_version]
                additional_artifacts.discard(partial_artifact)
                self._links.clear()

                self._resolved_requirements.append(
                    ResolvedRequirement(
                        requirement=requirement,
                        pin=project_name_and_version,
                        artifact=partial_artifact,
                        additional_artifacts=tuple(additional_artifacts),
                        via=via,
                    )
                )
            return self.Continue()

        match = self._saved_re.search(line)
        if match:
            self._saved.add(
                Pin.canonicalize(ProjectNameAndVersion.from_filename(match.group("filename")))
            )
            return self.Continue()

        if self.style in (LockStyle.SOURCES, LockStyle.UNIVERSAL):
            match = re.search(r"Found link (?P<url>[^\s]+)(?: \(from .*\))?, version: ", line)
            if match:
                project_name_and_version, partial_artifact = self._extract_resolve_data(
                    match.group("url")
                )
                self._links[project_name_and_version].add(partial_artifact)
                return self.Continue()

        if LockStyle.UNIVERSAL == self.style:
            match = re.search(
                r"Skipping link: none of the wheel's tags \([^)]+\) are compatible "
                r"\(run pip debug --verbose to show compatible tags\): "
                r"(?P<url>[^\s]+) ",
                line,
            )
            if match:
                project_name_and_version, partial_artifact = self._extract_resolve_data(
                    match.group("url")
                )
                self._links[project_name_and_version].add(partial_artifact)

        return self.Continue()

    def analysis_completed(self):
        # type: () -> None
        self._lock_request.resolve_handler(
            tuple(
                resolved_requirement
                for resolved_requirement in self._resolved_requirements
                if resolved_requirement.pin in self._saved
            )
        )


class _LogScrapeJob(Job):
    def __init__(
        self,
        command,  # type: Iterable[str]
        process,  # type: subprocess.Popen
        log,  # type: str
        log_analyzers,  # type: Iterable[_LogAnalyzer]
    ):
        self._log = log
        self._log_analyzers = list(log_analyzers)
        super(_LogScrapeJob, self).__init__(command, process)

    def _check_returncode(self, stderr=None):
        activated_analyzers = [
            analyzer
            for analyzer in self._log_analyzers
            if analyzer.should_collect(self._process.returncode)
        ]
        if activated_analyzers:
            collected = []
            with open(self._log, "r") as fp:
                for line in fp:
                    if not activated_analyzers:
                        break
                    for index, analyzer in enumerate(activated_analyzers):
                        result = analyzer.analyze(line)
                        if isinstance(result.data, ErrorMessage):
                            collected.append(result.data)
                        if isinstance(result, _LogAnalyzer.Complete):
                            activated_analyzers.pop(index).analysis_completed()
                            if not activated_analyzers:
                                break
            for analyzer in activated_analyzers:
                analyzer.analysis_completed()
            os.unlink(self._log)
            stderr = (stderr or b"") + "".join(collected).encode("utf-8")
        super(_LogScrapeJob, self)._check_returncode(stderr=stderr)


@attr.s(frozen=True)
class Pip(object):
    # N.B.: The following environment variables are used by the to control Pip at runtime and must
    # be kept in-sync with `runtime_patches.py`.
    _PATCHED_MARKERS_FILE_ENV_VAR_NAME = "_PEX_PATCHED_MARKERS_FILE"
    _PATCHED_TAGS_FILE_ENV_VAR_NAME = "_PEX_PATCHED_TAGS_FILE"
    _SKIP_MARKERS_ENV_VAR_NAME = "_PEX_SKIP_MARKERS"
    _PYTHON_VERSIONS_FILE_ENV_VAR_NAME = "_PEX_PYTHON_VERSIONS_FILE"

    @classmethod
    def create(
        cls,
        path,  # type: str
        interpreter=None,  # type: Optional[PythonInterpreter]
    ):
        # type: (...) -> Pip
        """Creates a pip tool with PEX isolation at path.

        :param path: The path to assemble the pip tool at.
        :param interpreter: The interpreter to run Pip with. The current interpreter by default.
        :return: The path of a PEX that can be used to execute Pip in isolation.
        """
        pip_interpreter = interpreter or PythonInterpreter.get()
        pip_pex_path = os.path.join(path, isolated().pex_hash)
        with atomic_directory(pip_pex_path, exclusive=True) as chroot:
            if not chroot.is_finalized():
                from pex.pex_builder import PEXBuilder

                isolated_pip_builder = PEXBuilder(path=chroot.work_dir)
                isolated_pip_builder.info.venv = True
                for dist_location in third_party.expose(["pip", "setuptools", "wheel"]):
                    isolated_pip_builder.add_dist_location(dist=dist_location)
                with named_temporary_file(prefix="", suffix=".py", mode="wb") as fp:
                    fp.write(pkgutil.get_data(__name__, "runtime_patches.py"))
                    fp.close()
                    isolated_pip_builder.set_executable(fp.name, "__pex_patched_pip__.py")
                isolated_pip_builder.freeze()
        return cls(ensure_venv(PEX(pip_pex_path, interpreter=pip_interpreter)))

    _pip_pex_path = attr.ib()  # type: str

    @staticmethod
    def _calculate_resolver_version(package_index_configuration=None):
        # type: (Optional[PackageIndexConfiguration]) -> ResolverVersion.Value
        return (
            package_index_configuration.resolver_version
            if package_index_configuration
            else ResolverVersion.PIP_LEGACY
        )

    @classmethod
    def _calculate_resolver_version_args(
        cls,
        interpreter,  # type: PythonInterpreter
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
    ):
        # type: (...) -> Iterator[str]
        resolver_version = cls._calculate_resolver_version(
            package_index_configuration=package_index_configuration
        )
        # N.B.: The pip default resolver depends on the python it is invoked with. For Python 2.7
        # Pip defaults to the legacy resolver and for Python 3 Pip defaults to the 2020 resolver.
        # Further, Pip warns when you do not use the default resolver version for the interpreter
        # in play. To both avoid warnings and set the correct resolver version, we need
        # to only set the resolver version when it's not the default for the interpreter in play:
        if resolver_version == ResolverVersion.PIP_2020 and interpreter.version[0] == 2:
            yield "--use-feature"
            yield "2020-resolver"
        elif resolver_version == ResolverVersion.PIP_LEGACY and interpreter.version[0] == 3:
            yield "--use-deprecated"
            yield "legacy-resolver"

    def _spawn_pip_isolated(
        self,
        args,  # type: Iterable[str]
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
        cache=None,  # type: Optional[str]
        interpreter=None,  # type: Optional[PythonInterpreter]
        pip_verbosity=0,  # type: int
        extra_env=None,  # type: Optional[Dict[str, str]]
        **popen_kwargs  # type: Any
    ):
        # type: (...) -> Tuple[List[str], subprocess.Popen]
        pip_args = [
            # We vendor the version of pip we want so pip should never check for updates.
            "--disable-pip-version-check",
            # If we want to warn about a version of python we support, we should do it, not pip.
            "--no-python-version-warning",
            # If pip encounters a duplicate file path during its operations we don't want it to
            # prompt and we'd also like to know about this since it should never occur. We leverage
            # the pip global option:
            # --exists-action <action>
            #   Default action when a path already exists: (s)witch, (i)gnore, (w)ipe, (b)ackup,
            #   (a)bort.
            "--exists-action",
            "a",
        ]
        python_interpreter = interpreter or PythonInterpreter.get()
        pip_args.extend(
            self._calculate_resolver_version_args(
                python_interpreter, package_index_configuration=package_index_configuration
            )
        )
        if not package_index_configuration or package_index_configuration.isolated:
            # Don't read PIP_ environment variables or pip configuration files like
            # `~/.config/pip/pip.conf`.
            pip_args.append("--isolated")

        # The max pip verbosity is -vvv and for pex it's -vvvvvvvvv; so we scale down by a factor
        # of 3.
        pip_verbosity = pip_verbosity or (ENV.PEX_VERBOSE // 3)
        if pip_verbosity > 0:
            pip_args.append("-{}".format("v" * pip_verbosity))
        else:
            pip_args.append("-q")

        if cache:
            pip_args.extend(["--cache-dir", cache])
        else:
            pip_args.append("--no-cache-dir")

        command = pip_args + list(args)

        # N.B.: Package index options in Pep always have the same option names, but they are
        # registered as subcommand-specific, so we must append them here _after_ the pip subcommand
        # specified in `args`.
        if package_index_configuration:
            command.extend(package_index_configuration.args)

        extra_env = extra_env or {}
        if package_index_configuration:
            extra_env.update(package_index_configuration.env)

        with ENV.strip().patch(
            PEX_ROOT=cache or ENV.PEX_ROOT,
            PEX_VERBOSE=str(ENV.PEX_VERBOSE),
            __PEX_UNVENDORED__="1",
            **extra_env
        ) as env:
            # Guard against API calls from environment with ambient PYTHONPATH preventing pip PEX
            # bootstrapping. See: https://github.com/pantsbuild/pex/issues/892
            pythonpath = env.pop("PYTHONPATH", None)
            if pythonpath:
                TRACER.log(
                    "Scrubbed PYTHONPATH={} from the pip PEX environment.".format(pythonpath), V=3
                )

            # Pip has no discernable stdout / stderr discipline with its logging. Pex guarantees
            # stdout will only contain useable (parseable) data and all logging will go to stderr.
            # To uphold the Pex standard, force Pip to comply by re-directing stdout to stderr.
            #
            # See:
            # + https://github.com/pantsbuild/pex/issues/1267
            # + https://github.com/pypa/pip/issues/9420
            if "stdout" not in popen_kwargs:
                popen_kwargs["stdout"] = sys.stderr.fileno()

            args = [self._pip_pex_path] + command
            return args, subprocess.Popen(args=args, env=env, **popen_kwargs)

    def _spawn_pip_isolated_job(
        self,
        args,  # type: Iterable[str]
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
        cache=None,  # type: Optional[str]
        interpreter=None,  # type: Optional[PythonInterpreter]
        pip_verbosity=0,  # type: int
        finalizer=None,  # type: Optional[Callable[[int], None]]
        extra_env=None,  # type: Optional[Dict[str, str]]
        **popen_kwargs  # type: Any
    ):
        # type: (...) -> Job
        command, process = self._spawn_pip_isolated(
            args,
            package_index_configuration=package_index_configuration,
            cache=cache,
            interpreter=interpreter,
            pip_verbosity=pip_verbosity,
            extra_env=extra_env,
            **popen_kwargs
        )
        return Job(command=command, process=process, finalizer=finalizer)

    def _iter_platform_args(
        self,
        platform,  # type: str
        impl,  # type: str
        version,  # type: str
        abi,  # type: str
        manylinux=None,  # type: Optional[str]
    ):
        # type: (...) -> Iterator[str]

        # N.B.: Pip supports passing multiple --platform and --abi. We pass multiple --platform to
        # support the following use case 1st surfaced by Twitter in 2018:
        #
        # An organization has its own index or find-links repository where it publishes wheels built
        # for linux machines it runs. Critically, all those machines present uniform kernel and
        # library ABIs for the purposes of python code that organization runs on those machines.
        # As such, the organization can build non-manylinux-compliant wheels and serve these wheels
        # from its private index / find-links repository with confidence these wheels will work on
        # the machines it controls. This is in contrast to the public PyPI index which does not
        # allow non-manylinux-compliant wheels to be uploaded at all since the wheels it serves can
        # be used on unknown target linux machines (for background on this, see:
        # https://www.python.org/dev/peps/pep-0513/#rationale). If that organization wishes to
        # consume both its own custom-built wheels as well as other manylinux-compliant wheels in
        # the same application, it needs to advertise that the target machine supports both
        # `linux_x86_64` wheels and `manylinux2014_x86_64` wheels (for example).
        if manylinux and platform.startswith("linux"):
            yield "--platform"
            yield platform.replace("linux", manylinux, 1)

        yield "--platform"
        yield platform

        yield "--implementation"
        yield impl

        yield "--python-version"
        yield version

        yield "--abi"
        yield abi

    def spawn_download_distributions(
        self,
        download_dir,  # type: str
        requirements=None,  # type: Optional[Iterable[str]]
        requirement_files=None,  # type: Optional[Iterable[str]]
        constraint_files=None,  # type: Optional[Iterable[str]]
        allow_prereleases=False,  # type: bool
        transitive=True,  # type: bool
        target=None,  # type: Optional[Target]
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
        cache=None,  # type: Optional[str]
        build=True,  # type: bool
        use_wheel=True,  # type: bool
        prefer_older_binary=False,  # type: bool
        use_pep517=None,  # type: Optional[bool]
        build_isolation=True,  # type: bool
        lock_request=None,  # type: Optional[LockRequest]
    ):
        # type: (...) -> Job
        target = target or targets.current()
        locker = Locker(lock_request, download_dir) if lock_request else None

        if not use_wheel:
            if not build:
                raise ValueError(
                    "Cannot both ignore wheels (use_wheel=False) and refrain from building "
                    "distributions (build=False)."
                )
            elif not isinstance(target, LocalInterpreter):
                raise ValueError(
                    "Cannot ignore wheels (use_wheel=False) when resolving for a platform: "
                    "{}".format(target.platform)
                )

        download_cmd = ["download", "--dest", download_dir]
        extra_env = {}  # type: Dict[str, str]

        if not isinstance(target, LocalInterpreter) or not build:
            # If we're not targeting a local interpreter, we can't build wheels from sdists.
            download_cmd.extend(["--only-binary", ":all:"])

        if not use_wheel:
            download_cmd.extend(["--no-binary", ":all:"])

        if prefer_older_binary:
            download_cmd.append("--prefer-binary")

        if use_pep517 is not None:
            download_cmd.append("--use-pep517" if use_pep517 else "--no-use-pep517")

        if not build_isolation:
            download_cmd.append("--no-build-isolation")
            extra_env.update(PEP517_BACKEND_PATH=os.pathsep.join(sys.path))

        if allow_prereleases:
            download_cmd.append("--pre")

        if not transitive:
            download_cmd.append("--no-deps")

        if requirement_files:
            for requirement_file in requirement_files:
                download_cmd.extend(["--requirement", requirement_file])

        if constraint_files:
            for constraint_file in constraint_files:
                download_cmd.extend(["--constraint", constraint_file])

        if requirements:
            download_cmd.extend(requirements)

        log_analyzers = []  # type: List[_LogAnalyzer]

        if locker:
            log_analyzers.append(locker)

        interpreter = target.get_interpreter()
        if locker and LockStyle.UNIVERSAL == locker.style:
            extra_env[self._SKIP_MARKERS_ENV_VAR_NAME] = "1"
            if locker.requires_python:
                version_info_dir = safe_mkdtemp()
                with TRACER.timed(
                    "Calculating compatible python versions for {}".format(locker.requires_python)
                ):
                    python_full_versions = list(iter_compatible_versions(locker.requires_python))
                with open(os.path.join(version_info_dir, "python_full_versions.json"), "w") as fp:
                    json.dump(python_full_versions, fp)
                extra_env[self._PYTHON_VERSIONS_FILE_ENV_VAR_NAME] = fp.name
        elif not isinstance(target, LocalInterpreter):
            # Pip evaluates environment markers in the context of the ambient interpreter instead of
            # failing when encountering them, ignoring them or doing what we do here: evaluate those
            # environment markers we know but fail for those we don't.
            patches_dir = safe_mkdtemp()
            patched_environment = target.marker_environment.as_dict()
            with open(os.path.join(patches_dir, "markers.json"), "w") as markers_fp:
                json.dump(patched_environment, markers_fp)
            extra_env[self._PATCHED_MARKERS_FILE_ENV_VAR_NAME] = markers_fp.name

            if isinstance(target, AbbreviatedPlatform):
                # We're either resolving for a different host / platform or a different interpreter
                # for the current platform that we have no access to; so we need to let pip know
                # and not otherwise pickup platform info from the interpreter we execute pip with.
                # Pip will determine the compatible platform tags using this information.
                platform = target.platform
                manylinux = target.manylinux
                download_cmd.extend(
                    self._iter_platform_args(
                        platform=platform.platform,
                        impl=platform.impl,
                        version=platform.version,
                        abi=platform.abi,
                        manylinux=manylinux,
                    )
                )
            elif isinstance(target, CompletePlatform):
                compatible_tags = target.supported_tags
                if compatible_tags:
                    with open(os.path.join(patches_dir, "tags.json"), "w") as tags_fp:
                        json.dump(compatible_tags.to_string_list(), tags_fp)
                    extra_env[self._PATCHED_TAGS_FILE_ENV_VAR_NAME] = tags_fp.name

            log_analyzers.append(_Issue10050Analyzer(platform=target.platform))
            TRACER.log(
                "Patching environment markers for {} with {}".format(target, patched_environment),
                V=3,
            )

        # The Pip 2020 resolver hides useful dependency conflict information in stdout interspersed
        # with other information we want to suppress. We jump though some hoops here to get at that
        # information and surface it on stderr. See: https://github.com/pypa/pip/issues/9420.
        if (
            self._calculate_resolver_version(
                package_index_configuration=package_index_configuration
            )
            == ResolverVersion.PIP_2020
        ):
            log_analyzers.append(_Issue9420Analyzer())

        log = None
        popen_kwargs = {}
        if log_analyzers:
            log = os.path.join(safe_mkdtemp(), "pip.log")
            download_cmd = ["--log", log] + download_cmd
            # N.B.: The `pip -q download ...` command is quiet but
            # `pip -q --log log.txt download ...` leaks download progress bars to stdout. We work
            # around this by sending stdout to the bit bucket.
            popen_kwargs["stdout"] = open(os.devnull, "wb")

        command, process = self._spawn_pip_isolated(
            download_cmd,
            package_index_configuration=package_index_configuration,
            cache=cache,
            interpreter=interpreter,
            pip_verbosity=0,
            extra_env=extra_env,
            **popen_kwargs
        )
        if log:
            return _LogScrapeJob(command, process, log, log_analyzers)
        else:
            return Job(command, process)

    def spawn_build_wheels(
        self,
        distributions,  # type: Iterable[str]
        wheel_dir,  # type: str
        interpreter=None,  # type: Optional[PythonInterpreter]
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
        cache=None,  # type: Optional[str]
        prefer_older_binary=False,  # type: bool
        use_pep517=None,  # type: Optional[bool]
        build_isolation=True,  # type: bool
        verify=True,  # type: bool
    ):
        # type: (...) -> Job
        wheel_cmd = ["wheel", "--no-deps", "--wheel-dir", wheel_dir]
        extra_env = {}  # type: Dict[str, str]

        # It's not clear if Pip's implementation of PEP-517 builds respects this option for
        # resolving build dependencies, but in case it is we pass it.
        if use_pep517 is not False and prefer_older_binary:
            wheel_cmd.append("--prefer-binary")

        if use_pep517 is not None:
            wheel_cmd.append("--use-pep517" if use_pep517 else "--no-use-pep517")

        if not build_isolation:
            wheel_cmd.append("--no-build-isolation")
            interpreter = interpreter or PythonInterpreter.get()
            extra_env.update(PEP517_BACKEND_PATH=os.pathsep.join(interpreter.sys_path))

        if not verify:
            wheel_cmd.append("--no-verify")

        wheel_cmd.extend(distributions)

        return self._spawn_pip_isolated_job(
            wheel_cmd,
            # If the build leverages PEP-518 it will need to resolve build requirements.
            package_index_configuration=package_index_configuration,
            cache=cache,
            interpreter=interpreter,
            extra_env=extra_env,
        )

    def spawn_install_wheel(
        self,
        wheel,  # type: str
        install_dir,  # type: str
        compile=False,  # type: bool
        cache=None,  # type: Optional[str]
        target=None,  # type: Optional[Target]
    ):
        # type: (...) -> Job

        project_name_and_version = dist_metadata.project_name_and_version(wheel)
        assert project_name_and_version is not None, (
            "Should never fail to parse a wheel path into a project name and version, but "
            "failed to parse these from: {wheel}".format(wheel=wheel)
        )

        target = target or targets.current()
        interpreter = target.get_interpreter()
        if target.is_foreign:
            if compile:
                raise ValueError(
                    "Cannot compile bytecode for {} using {} because the wheel has a foreign "
                    "platform.".format(wheel, interpreter)
                )

        install_cmd = [
            "install",
            "--no-deps",
            "--no-index",
            "--only-binary",
            ":all:",
            # In `--prefix` scheme, Pip warns about installed scripts not being on $PATH. We fix
            # this when a PEX is turned into a venv.
            "--no-warn-script-location",
            # In `--prefix` scheme, Pip normally refuses to install a dependency already in the
            # `sys.path` of Pip itself since the requirement is already satisfied. Since `pip`,
            # `setuptools` and `wheel` are always in that `sys.path` (Our `pip.pex` venv PEX), we
            # force installation so that PEXes with dependencies on those projects get them properly
            # installed instead of skipped.
            "--force-reinstall",
            "--ignore-installed",
            # We're potentially installing a wheel for a foreign platform. This is just an
            # unpacking operation though; so we don't actually need to perform it with a target
            # platform compatible interpreter (except for scripts - which we deal with in fixup
            # install below).
            "--ignore-requires-python",
            "--prefix",
            install_dir,
        ]

        # The `--prefix` scheme causes Pip to refuse to install foreign wheels. It assumes those
        # wheels must be compatible with the current venv. Since we just install wheels in
        # individual chroots for later re-assembly on the `sys.path` at runtime or at venv install
        # time, we override this concern by forcing the wheel's tags to be considered compatible
        # with the current Pip install interpreter being used.
        compatible_tags = CompatibilityTags.from_wheel(wheel).extend(
            interpreter.identity.supported_tags
        )
        with open(os.path.join(safe_mkdtemp(), "tags.json"), "w") as tags_fp:
            json.dump(compatible_tags.to_string_list(), tags_fp)
        extra_env = {self._PATCHED_TAGS_FILE_ENV_VAR_NAME: tags_fp.name}

        install_cmd.append("--compile" if compile else "--no-compile")
        install_cmd.append(wheel)

        def fixup_install(returncode):
            if returncode != 0:
                return
            record = Record.from_prefix_install(
                prefix_dir=install_dir,
                project_name=project_name_and_version.project_name,
                version=project_name_and_version.version,
            )
            record.fixup_install(interpreter=interpreter)

        return self._spawn_pip_isolated_job(
            args=install_cmd,
            cache=cache,
            interpreter=interpreter,
            finalizer=fixup_install,
            extra_env=extra_env,
        )

    def spawn_debug(
        self,
        platform,  # type: str
        impl,  # type: str
        version,  # type: str
        abi,  # type: str
        manylinux=None,  # type: Optional[str]
    ):
        # type: (...) -> Job

        # N.B.: Pip gives fair warning:
        #   WARNING: This command is only meant for debugging. Do not use this with automation for
        #   parsing and getting these details, since the output and options of this command may
        #   change without notice.
        #
        # We suppress the warning by capturing stderr below. The information there will be dumped
        # only if the Pip command fails, which is what we want.

        debug_command = ["debug"]
        debug_command.extend(
            self._iter_platform_args(
                platform=platform,
                impl=impl,
                version=version,
                abi=abi,
                manylinux=manylinux,
            )
        )
        return self._spawn_pip_isolated_job(
            debug_command, pip_verbosity=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )


_PIP = {}  # type: Dict[Optional[PythonInterpreter], Pip]


def get_pip(interpreter=None):
    # type: (Optional[PythonInterpreter]) -> Pip
    """Returns a lazily instantiated global Pip object that is safe for un-coordinated use."""
    pip = _PIP.get(interpreter)
    if pip is None:
        pip = Pip.create(path=os.path.join(ENV.PEX_ROOT, "pip.pex"), interpreter=interpreter)
        _PIP[interpreter] = pip
    return pip
