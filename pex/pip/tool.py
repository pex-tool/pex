# coding=utf-8
# Copyright 2019 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import glob
import hashlib
import os
import re
import subprocess
import sys
import textwrap
from collections import deque

from pex import pex_warnings, targets
from pex.atomic_directory import atomic_directory
from pex.auth import PasswordEntry
from pex.cache.dirs import PipPexDir
from pex.common import safe_mkdir, safe_mkdtemp
from pex.compatibility import get_stderr_bytes_buffer, shlex_quote, urlparse
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import Requirement
from pex.interpreter import PythonInterpreter
from pex.jobs import Job
from pex.network_configuration import NetworkConfiguration
from pex.pep_427 import install_wheel_interpreter
from pex.pip import dependencies, foreign_platform
from pex.pip.download_observer import DownloadObserver, PatchSet
from pex.pip.log_analyzer import ErrorAnalyzer, ErrorMessage, LogAnalyzer, LogScrapeJob
from pex.pip.tailer import Tailer
from pex.pip.version import PipVersion, PipVersionValue
from pex.platforms import PlatformSpec
from pex.resolve.resolver_configuration import (
    BuildConfiguration,
    ReposConfiguration,
    ResolverVersion,
)
from pex.targets import Target
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    from typing import (
        Any,
        Callable,
        Dict,
        Iterable,
        Iterator,
        List,
        Mapping,
        Match,
        Optional,
        Sequence,
        Tuple,
    )

    import attr  # vendor:skip
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
        if indexes is not None and tuple(indexes) != ReposConfiguration().indexes:
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
        use_pip_config,  # type: bool
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
                ("PIP_CERT" if use_pip_config else "REQUESTS_CA_BUNDLE"),
                os.path.abspath(network_configuration.cert),
            )

        if network_configuration.client_cert:
            assert use_pip_config
            yield "PIP_CLIENT_CERT", os.path.abspath(network_configuration.client_cert)

    @classmethod
    def create(
        cls,
        pip_version=None,  # type: Optional[PipVersionValue]
        resolver_version=None,  # type: Optional[ResolverVersion.Value]
        indexes=None,  # type: Optional[Sequence[str]]
        find_links=None,  # type: Optional[Iterable[str]]
        network_configuration=None,  # type: Optional[NetworkConfiguration]
        password_entries=(),  # type: Iterable[PasswordEntry]
        use_pip_config=False,  # type: bool
        extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
        keyring_provider=None,  # type: Optional[str]
    ):
        # type: (...) -> PackageIndexConfiguration
        resolver_version = resolver_version or ResolverVersion.default(pip_version)
        network_configuration = network_configuration or NetworkConfiguration()

        # We must pass `--client-cert` via PIP_CLIENT_CERT to work around
        # https://github.com/pypa/pip/issues/5502. We can only do this by breaking Pip `--isolated`
        # mode.
        use_pip_config = use_pip_config or network_configuration.client_cert is not None

        return cls(
            pip_version=pip_version,
            resolver_version=resolver_version,
            network_configuration=network_configuration,
            args=cls._calculate_args(
                indexes=indexes, find_links=find_links, network_configuration=network_configuration
            ),
            env=cls._calculate_env(
                network_configuration=network_configuration, use_pip_config=use_pip_config
            ),
            use_pip_config=use_pip_config,
            extra_pip_requirements=extra_pip_requirements,
            password_entries=password_entries,
            keyring_provider=keyring_provider,
        )

    def __init__(
        self,
        resolver_version,  # type: ResolverVersion.Value
        network_configuration,  # type: NetworkConfiguration
        args,  # type: Iterable[str]
        env,  # type: Iterable[Tuple[str, str]]
        use_pip_config,  # type: bool
        password_entries=(),  # type: Iterable[PasswordEntry]
        pip_version=None,  # type: Optional[PipVersionValue]
        extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
        keyring_provider=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        self.resolver_version = resolver_version  # type: ResolverVersion.Value
        self.network_configuration = network_configuration  # type: NetworkConfiguration
        self.args = tuple(args)  # type: Iterable[str]
        self.env = dict(env)  # type: Mapping[str, str]
        self.use_pip_config = use_pip_config  # type: bool
        self.password_entries = password_entries  # type: Iterable[PasswordEntry]
        self.pip_version = pip_version  # type: Optional[PipVersionValue]
        self.extra_pip_requirements = extra_pip_requirements  # type: Tuple[Requirement, ...]
        self.keyring_provider = keyring_provider  # type: Optional[str]


if TYPE_CHECKING:
    from pex.pip.log_analyzer import ErrorAnalysis


@attr.s
class _Issue9420Analyzer(ErrorAnalyzer):
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


@attr.s
class _PexIssue2113Analyzer(ErrorAnalyzer):
    # Improves obscure error output described in: https://github.com/pex-tool/pex/issues/2113

    _strip = attr.ib(default=0, init=False)  # type: Optional[int]
    _command = attr.ib(default=None, init=False)  # type: Optional[str]
    _command_output = attr.ib(factory=list, init=False)  # type: List[str]
    _command_errored = attr.ib(default=None, init=False)  # type: Optional[Match]

    def analyze(self, line):
        # type: (str) -> ErrorAnalysis

        if self._command_errored:
            return self.Complete()

        match = re.match(r"^(?P<timestamp>\S+)\s+Running command (?P<command>.*)$", line)
        if match:
            self._strip = len(match.group("timestamp"))
            self._command = match.group("command")
            del self._command_output[:]
            self._command_output.append(line[self._strip :])
            return self.Continue()

        if self._command:
            self._command_errored = re.match(
                r"^\S+\s+ERROR:.*{command}".format(command=re.escape(self._command)), line
            )
            if self._command_errored:
                return self.Continue(
                    ErrorMessage("".join(self._command_output + [line[self._strip :]]))
                )
            self._command_output.append(line[self._strip :])

        return self.Continue()


@attr.s(frozen=True)
class PipVenv(object):
    venv_dir = attr.ib()  # type: str
    pex_hash = attr.ib()  # type: str
    execute_env = attr.ib(default=())  # type: Tuple[Tuple[str, str], ...]
    _execute_args = attr.ib(default=())  # type: Tuple[str, ...]

    def execute_args(self, *args):
        # type: (*str) -> List[str]
        return list(self._execute_args + args)

    def get_interpreter(self):
        # type: () -> PythonInterpreter
        return Virtualenv(self.venv_dir).interpreter


@attr.s(frozen=True)
class Pip(object):
    _PATCHES_PACKAGE_ENV_VAR_NAME = "_PEX_PIP_RUNTIME_PATCHES_PACKAGE"
    _PATCHES_PACKAGE_NAME = "_pex_pip_patches"

    _pip_pex = attr.ib()  # type: PipPexDir
    _pip_venv = attr.ib()  # type: PipVenv

    @property
    def venv_dir(self):
        # type: () -> str
        return self._pip_venv.venv_dir

    @property
    def pex_hash(self):
        # type: () -> str
        return self._pip_venv.pex_hash

    @property
    def version(self):
        # type: () -> PipVersionValue
        return self._pip_pex.version

    @property
    def pex_dir(self):
        # type: () -> PipPexDir
        return self._pip_pex

    @property
    def cache_dir(self):
        # type: () -> str
        return self._pip_pex.cache_dir

    @staticmethod
    def _calculate_resolver_version(package_index_configuration=None):
        # type: (Optional[PackageIndexConfiguration]) -> ResolverVersion.Value
        return (
            package_index_configuration.resolver_version
            if package_index_configuration
            else ResolverVersion.default()
        )

    def _calculate_resolver_version_args(
        self,
        interpreter,  # type: PythonInterpreter
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
    ):
        # type: (...) -> Iterator[str]
        resolver_version = self._calculate_resolver_version(
            package_index_configuration=package_index_configuration
        )
        # N.B.: The pip default resolver depends on the python it is invoked with. For Python 2.7
        # Pip defaults to the legacy resolver and for Python 3 Pip defaults to the 2020 resolver.
        # Further, Pip warns when you do not use the default resolver version for the interpreter
        # in play. To both avoid warnings and set the correct resolver version, we need
        # to only set the resolver version when it's not the default for the interpreter in play.
        # As an added constraint, the 2020-resolver feature was removed and made default in the
        # Pip 22.3 release.
        if (
            resolver_version == ResolverVersion.PIP_2020
            and interpreter.version[0] == 2
            and self.version.version < PipVersion.v22_3.version
        ):
            yield "--use-feature"
            yield "2020-resolver"
        elif resolver_version == ResolverVersion.PIP_LEGACY and interpreter.version[0] == 3:
            yield "--use-deprecated"
            yield "legacy-resolver"

    def _spawn_pip_isolated(
        self,
        args,  # type: Iterable[str]
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
        interpreter=None,  # type: Optional[PythonInterpreter]
        log=None,  # type: Optional[str]
        pip_verbosity=0,  # type: int
        extra_env=None,  # type: Optional[Dict[str, str]]
        **popen_kwargs  # type: Any
    ):
        # type: (...) -> Tuple[List[str], subprocess.Popen]
        pip_args = [
            # We vendor the version of pip we want so pip should never check for updates.
            "--disable-pip-version-check",
            # If pip encounters a duplicate file path during its operations we don't want it to
            # prompt and we'd also like to know about this since it should never occur. We leverage
            # the pip global option:
            # --exists-action <action>
            #   Default action when a path already exists: (s)witch, (i)gnore, (w)ipe, (b)ackup,
            #   (a)bort.
            "--exists-action",
            "a",
            # We are not interactive.
            "--no-input",
        ]
        if self.version < PipVersion.v25_0:
            # If we want to warn about a version of python we support, we should do it, not pip.
            # That said, the option does nothing in Pip 25.0 and is deprecated and slated for
            # removal.
            pip_args.append("--no-python-version-warning")

        python_interpreter = interpreter or PythonInterpreter.get()
        pip_args.extend(
            self._calculate_resolver_version_args(
                python_interpreter, package_index_configuration=package_index_configuration
            )
        )
        if not package_index_configuration or not package_index_configuration.use_pip_config:
            # Don't read PIP_ environment variables or pip configuration files like
            # `~/.config/pip/pip.conf`.
            pip_args.append("--isolated")

        # Configure a keychain provider if so configured and the version of Pip supports the option.
        # Warn the user if Pex cannot pass the `--keyring-provider` option and suggest a solution.
        if package_index_configuration and package_index_configuration.keyring_provider:
            if self.version.version >= PipVersion.v23_1.version:
                pip_args.append("--keyring-provider")
                pip_args.append(package_index_configuration.keyring_provider)
            else:
                warn_msg = textwrap.dedent(
                    """
                    The --keyring-provider option is set to `{PROVIDER}`, but Pip v{THIS_VERSION} does not support the
                    `--keyring-provider` option (which is only available in Pip v{VERSION_23_1} and later versions).
                    Consequently, Pex is ignoring the --keyring-provider option for this particular Pip invocation.

                    Note: If this Pex invocation fails, it may be because Pex is trying to use its vendored Pip v{VENDORED_VERSION}
                    to bootstrap a newer Pip version which does support `--keyring-provider`, but you configured Pex/Pip
                    to use a Python package index which is not available without additional authentication.

                    In that case, you might wish to consider manually creating a `find-links` directory with that newer version
                    of Pip, so that Pex will still be able to install the newer version of Pip from the `find-links` directory
                    (which does not require authentication).
                    """.format(
                        PROVIDER=package_index_configuration.keyring_provider,
                        THIS_VERSION=self.version.version,
                        VERSION_23_1=PipVersion.v23_1,
                        VENDORED_VERSION=PipVersion.VENDORED.version,
                    )
                )
                pex_warnings.warn(warn_msg)

        if log:
            pip_args.append("--log")
            pip_args.append(log)

        # The max pip verbosity is -vvv and for pex it's -vvvvvvvvv; so we scale down by a factor
        # of 3.
        pip_verbosity = pip_verbosity or (ENV.PEX_VERBOSE // 3)
        if pip_verbosity > 0:
            pip_args.append("-{}".format("v" * pip_verbosity))
        else:
            pip_args.append("-q")

        pip_args.extend(["--cache-dir", self.cache_dir])

        command = pip_args + list(args)

        # N.B.: Package index options in Pep always have the same option names, but they are
        # registered as subcommand-specific, so we must append them here _after_ the pip subcommand
        # specified in `args`.
        if package_index_configuration:
            command.extend(package_index_configuration.args)

        extra_env = extra_env or {}
        if package_index_configuration:
            extra_env.update(package_index_configuration.env)

        # Ensure the pip cache (`http/` and `wheels/` dirs) is housed in the same partition as the
        # temporary directories it creates. This is needed to ensure atomic filesystem operations
        # since Pip relies upon `shutil.move` which is only atomic when `os.rename` can be used.
        # See https://github.com/pex-tool/pex/issues/1776 for an example of the issues non-atomic
        # moves lead to in the `pip wheel` case.
        pip_tmpdir = os.path.join(self.cache_dir, ".tmp")
        safe_mkdir(pip_tmpdir)
        extra_env.update(TMPDIR=pip_tmpdir)

        with ENV.strip().patch(
            PEX_ROOT=ENV.PEX_ROOT,
            PEX_VERBOSE=str(ENV.PEX_VERBOSE),
            __PEX_UNVENDORED__="setuptools",
            **extra_env
        ) as env:
            # Guard against API calls from environment with ambient PYTHONPATH preventing pip PEX
            # bootstrapping. See: https://github.com/pex-tool/pex/issues/892
            pythonpath = env.pop("PYTHONPATH", None)
            if pythonpath:
                TRACER.log(
                    "Scrubbed PYTHONPATH={} from the pip PEX environment.".format(pythonpath), V=3
                )

            # Pip has no discernible stdout / stderr discipline with its logging. Pex guarantees
            # stdout will only contain usable (parseable) data and all logging will go to stderr.
            # To uphold the Pex standard, force Pip to comply by re-directing stdout to stderr.
            #
            # See:
            # + https://github.com/pex-tool/pex/issues/1267
            # + https://github.com/pypa/pip/issues/9420
            if "stdout" not in popen_kwargs:
                popen_kwargs["stdout"] = sys.stderr.fileno()
            popen_kwargs.update(stderr=subprocess.PIPE)

            env.update(self._pip_venv.execute_env)
            args = self._pip_venv.execute_args(*command)

            rendered_env = " ".join(
                "{}={}".format(key, shlex_quote(value)) for key, value in env.items()
            )
            rendered_args = " ".join(shlex_quote(s) for s in args)
            TRACER.log("Executing: {} {}".format(rendered_env, rendered_args), V=3)

            return args, subprocess.Popen(args=args, env=env, **popen_kwargs)

    def _spawn_pip_isolated_job(
        self,
        args,  # type: Iterable[str]
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
        interpreter=None,  # type: Optional[PythonInterpreter]
        log=None,  # type: Optional[str]
        pip_verbosity=0,  # type: int
        finalizer=None,  # type: Optional[Callable[[int], None]]
        extra_env=None,  # type: Optional[Dict[str, str]]
        **popen_kwargs  # type: Any
    ):
        # type: (...) -> Job
        command, process = self._spawn_pip_isolated(
            args,
            package_index_configuration=package_index_configuration,
            interpreter=interpreter,
            log=log,
            pip_verbosity=pip_verbosity,
            extra_env=extra_env,
            **popen_kwargs
        )
        return Job(command=command, process=process, finalizer=finalizer, context="pip")

    @staticmethod
    def _iter_build_configuration_options(build_configuration):
        # type: (BuildConfiguration) -> Iterator[str]

        # N.B.: BuildConfiguration maintains invariants that ensure --only-binary, --no-binary,
        # --prefer-binary, --use-pep517 and --no-build-isolation are coherent.

        if not build_configuration.allow_builds:
            yield "--only-binary"
            yield ":all:"
        elif not build_configuration.allow_wheels:
            yield "--no-binary"
            yield ":all:"
        else:
            for project in build_configuration.only_wheels:
                yield "--only-binary"
                yield str(project)
            for project in build_configuration.only_builds:
                yield "--no-binary"
                yield str(project)

        if build_configuration.prefer_older_binary:
            yield "--prefer-binary"

        if build_configuration.use_pep517 is not None:
            yield "--use-pep517" if build_configuration.use_pep517 else "--no-use-pep517"

        if not build_configuration.build_isolation:
            yield "--no-build-isolation"

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
        build_configuration=BuildConfiguration(),  # type: BuildConfiguration
        observer=None,  # type: Optional[DownloadObserver]
        dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
        log=None,  # type: Optional[str]
    ):
        # type: (...) -> Job
        target = target or targets.current()

        download_cmd = ["download", "--dest", download_dir]
        extra_env = {}  # type: Dict[str, str]
        pex_extra_sys_path = []  # type: List[str]

        download_cmd.extend(self._iter_build_configuration_options(build_configuration))
        if not build_configuration.build_isolation:
            pex_extra_sys_path.extend(sys.path)

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

        foreign_platform_observer = foreign_platform.patch(target)
        if (
            foreign_platform_observer
            and foreign_platform_observer.patch_set.patches
            and observer
            and observer.patch_set.patches
        ):
            raise ValueError(
                "Can only have one patch for Pip code, but, in addition to patching for a foreign "
                "platform, asked to patch code for {observer}.".format(observer=observer)
            )

        log_analyzers = []  # type: List[LogAnalyzer]
        patch_set = PatchSet()
        for obs in (
            foreign_platform_observer,
            observer,
            dependencies.patch(dependency_configuration),
        ):
            if obs:
                if obs.analyzer:
                    log_analyzers.append(obs.analyzer)
                patch_set = patch_set + obs.patch_set

        if patch_set:
            extra_env.update(patch_set.env)
            extra_sys_path = patch_set.emit_patches(package=self._PATCHES_PACKAGE_NAME)
            if extra_sys_path:
                pex_extra_sys_path.extend(extra_sys_path)
                extra_env[self._PATCHES_PACKAGE_ENV_VAR_NAME] = self._PATCHES_PACKAGE_NAME

        if pex_extra_sys_path:
            extra_env["PEX_EXTRA_SYS_PATH"] = os.pathsep.join(pex_extra_sys_path)

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

        # Most versions of Pip hide useful information when a metadata build command fails; this
        # analyzer brings that build failure information to the fore.
        log_analyzers.append(_PexIssue2113Analyzer())

        popen_kwargs = {}
        finalizer = None
        log = log or os.path.join(safe_mkdtemp(prefix="pex-pip-log."), "pip.log")

        # N.B.: The `pip -q download ...` command is quiet but
        # `pip -q --log log.txt download ...` leaks download progress bars to stdout. We work
        # around this by sending stdout to the bit bucket.
        popen_kwargs["stdout"] = open(os.devnull, "wb")

        if ENV.PEX_VERBOSE > 0:
            tailer = Tailer.tail(
                path=log,
                output=get_stderr_bytes_buffer(),
                filters=(
                    re.compile(
                        r"^.*(pip is looking at multiple versions of [^\s+] to determine "
                        r"which version is compatible with other requirements\. This could "
                        r"take a while\.).*$"
                    ),
                    re.compile(
                        r"^.*(This is taking longer than usual. You might need to provide "
                        r"the dependency resolver with stricter constraints to reduce "
                        r"runtime\. If you want to abort this run, you can press "
                        r"Ctrl \+ C to do so\. To improve how pip performs, tell us what "
                        r"happened here: https://pip\.pypa\.io/surveys/backtracking).*$"
                    ),
                ),
            )

            def finalizer(_):
                # type: (int) -> None
                tailer.stop()

        command, process = self._spawn_pip_isolated(
            download_cmd,
            package_index_configuration=package_index_configuration,
            interpreter=target.get_interpreter(),
            log=log,
            pip_verbosity=0,
            extra_env=extra_env,
            **popen_kwargs
        )
        return LogScrapeJob(command, process, log, log_analyzers, finalizer=finalizer)

    def _ensure_wheel_installed(self, package_index_configuration=None):
        # type: (Optional[PackageIndexConfiguration]) -> None
        pip_interpreter = self._pip_venv.get_interpreter()
        with atomic_directory(
            os.path.join(
                self.cache_dir,
                ".wheel-install",
                hashlib.sha1(pip_interpreter.binary.encode("utf-8")).hexdigest(),
            )
        ) as atomic_dir:
            if not atomic_dir.is_finalized():
                self.spawn_download_distributions(
                    download_dir=atomic_dir.work_dir,
                    requirements=[str(self.version.wheel_requirement)],
                    package_index_configuration=package_index_configuration,
                    build_configuration=BuildConfiguration.create(allow_builds=False),
                ).wait()
                for wheel in glob.glob(os.path.join(atomic_dir.work_dir, "*.whl")):
                    install_wheel_interpreter(wheel_path=wheel, interpreter=pip_interpreter)

    def spawn_build_wheels(
        self,
        distributions,  # type: Iterable[str]
        wheel_dir,  # type: str
        interpreter=None,  # type: Optional[PythonInterpreter]
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
        build_configuration=BuildConfiguration(),  # type: BuildConfiguration
        verify=True,  # type: bool
    ):
        # type: (...) -> Job

        if self.version is PipVersion.VENDORED:
            self._ensure_wheel_installed(package_index_configuration=package_index_configuration)

        wheel_cmd = ["wheel", "--no-deps", "--wheel-dir", wheel_dir]
        extra_env = {}  # type: Dict[str, str]

        # It's not clear if Pip's implementation of PEP-517 builds respects all build configuration
        # options for resolving build dependencies, but in case it does, we pass them all.
        wheel_cmd.extend(self._iter_build_configuration_options(build_configuration))
        if not build_configuration.build_isolation:
            interpreter = interpreter or PythonInterpreter.get()
            extra_env.update(PEX_EXTRA_SYS_PATH=os.pathsep.join(interpreter.sys_path))

        if not verify:
            wheel_cmd.append("--no-verify")

        wheel_cmd.extend(distributions)

        return self._spawn_pip_isolated_job(
            wheel_cmd,
            # If the build leverages PEP-518 it will need to resolve build requirements.
            package_index_configuration=package_index_configuration,
            interpreter=interpreter,
            extra_env=extra_env,
        )

    def spawn_debug(
        self,
        platform_spec,  # type: PlatformSpec
        manylinux=None,  # type: Optional[str]
        log=None,  # type: Optional[str]
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
            foreign_platform.iter_platform_args(platform_spec, manylinux=manylinux)
        )
        return self._spawn_pip_isolated_job(
            debug_command, log=log, pip_verbosity=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

    def spawn_cache_remove(self, wheel_name_glob):
        # type: (str) -> Job
        return self._spawn_pip_isolated_job(
            args=["cache", "remove", wheel_name_glob],
            pip_verbosity=1,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def spawn_cache_list(self):
        # type: () -> Job
        return self._spawn_pip_isolated_job(
            args=["cache", "list", "--format", "abspath"],
            pip_verbosity=1,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
