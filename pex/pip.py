# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import base64
import csv
import fileinput
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
from abc import abstractmethod
from collections import deque
from contextlib import closing
from textwrap import dedent

from pex import dist_metadata, third_party
from pex.common import atomic_directory, is_script, safe_mkdtemp
from pex.compatibility import urlparse
from pex.dist_metadata import ProjectNameAndVersion
from pex.distribution_target import DistributionTarget
from pex.finders import DistributionScript
from pex.interpreter import PythonInterpreter
from pex.jobs import Job
from pex.network_configuration import NetworkConfiguration
from pex.pex import PEX
from pex.pex_bootstrapper import ensure_venv
from pex.pex_info import PexInfo
from pex.platforms import Platform
from pex.third_party import isolated
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper, named_temporary_file
from pex.variables import ENV

if TYPE_CHECKING:
    import attr  # vendor:skip

    from typing import (
        Any,
        Callable,
        Dict,
        Iterable,
        Iterator,
        List,
        Mapping,
        Optional,
        Protocol,
        Tuple,
        Union,
    )

    class CSVWriter(Protocol):
        def writerow(self, row):
            # type: (Iterable[Union[str, int]]) -> None
            pass


else:
    from pex.third_party import attr


class ResolverVersion(object):
    class Value(object):
        def __init__(self, value):
            # type: (str) -> None
            self.value = value

        def __repr__(self):
            # type: () -> str
            return repr(self.value)

    PIP_LEGACY = Value("pip-legacy-resolver")
    PIP_2020 = Value("pip-2020-resolver")

    values = PIP_LEGACY, PIP_2020

    @classmethod
    def for_value(cls, value):
        # type: (str) -> ResolverVersion.Value
        for v in cls.values:
            if v.value == value:
                return v
        raise ValueError(
            "{!r} of type {} must be one of {}".format(
                value, type(value), ", ".join(map(repr, cls.values))
            )
        )


class PackageIndexConfiguration(object):
    @staticmethod
    def _calculate_args(
        indexes=None,  # type: Optional[List[str]]
        find_links=None,  # type: Optional[List[str]]
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

        if network_configuration.proxy:
            yield "--proxy"
            yield network_configuration.proxy

    @staticmethod
    def _calculate_env(
        network_configuration,  # type: NetworkConfiguration
        isolated,  # type: bool
    ):
        # type: (...) -> Iterator[Tuple[str, str]]
        if network_configuration.cert:
            # We use the backdoor of requests (which is vendored by Pip to handle all network
            # operations) support for REQUESTS_CA_BUNDLE when possible to continue to allow Pip to
            # operate in `--isolated` mode.
            yield ("REQUESTS_CA_BUNDLE" if isolated else "PIP_CERT"), network_configuration.cert

        if network_configuration.client_cert:
            assert not isolated
            yield "PIP_CLIENT_CERT", network_configuration.client_cert

    @classmethod
    def create(
        cls,
        resolver_version=None,  # type: Optional[ResolverVersion.Value]
        indexes=None,  # type: Optional[List[str]]
        find_links=None,  # type: Optional[List[str]]
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


class _LogAnalyzer(object):
    @attr.s(frozen=True)
    class Complete(object):
        text = attr.ib(default=None)  # type: Optional[str]

    @attr.s(frozen=True)
    class Continue(object):
        text = attr.ib(default=None)  # type: Optional[str]

    @abstractmethod
    def analyze(self, line):
        # type: (str) -> Union[Complete, Continue]
        """Analyze the given log line.

        Returns a value indicating whether or not analysis is complete. The value may contain text
        that should be reported as part of the error analysis.
        """


class _Issue9420Analyzer(_LogAnalyzer):
    # Works around: https://github.com/pypa/pip/issues/9420

    def __init__(self):
        # type: () -> None
        self._strip = None  # type: Optional[int]

    def analyze(self, line):
        # type: (str) -> Union[_LogAnalyzer.Complete, _LogAnalyzer.Continue]
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
                return self.Continue(line[self._strip :])
        return self.Continue()


@attr.s(frozen=True)
class _Issue10050Analyzer(_LogAnalyzer):
    # Part of the workaround for: https://github.com/pypa/pip/issues/10050

    _platform = attr.ib()  # type: Platform

    def analyze(self, line):
        # type: (str) -> Union[_LogAnalyzer.Complete, _LogAnalyzer.Continue]
        # N.B.: Pip --log output looks like:
        # 2021-06-20T19:06:00,981 pip._vendor.packaging.markers.UndefinedEnvironmentName: 'python_full_version' does not exist in evaluation environment.
        match = re.match(
            r"^[^ ]+ pip._vendor.packaging.markers.UndefinedEnvironmentName: "
            r"(?P<missing_marker>.*)\.$",
            line,
        )
        if match:
            return self.Complete(
                "Failed to resolve for platform {}. Resolve requires evaluation of unknown "
                "environment marker: {}.".format(self._platform, match.group("missing_marker"))
            )
        return self.Continue()


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
        if self._process.returncode != 0:
            collected = []
            with open(self._log, "r") as fp:
                for line in fp:
                    if not self._log_analyzers:
                        break
                    for index, analyzer in enumerate(self._log_analyzers):
                        result = analyzer.analyze(line)
                        if result.text:
                            collected.append(result.text)
                        if isinstance(result, _LogAnalyzer.Complete):
                            self._log_analyzers.pop(index)
                            if not self._log_analyzers:
                                break
            os.unlink(self._log)
            stderr = (stderr or b"") + "".join(collected).encode("utf-8")
        super(_LogScrapeJob, self)._check_returncode(stderr=stderr)


class Pip(object):
    _PATCHED_MARKERS_FILE_ENV_VAR_NAME = "_PEX_PATCHED_MARKERS_FILE"

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
            if not chroot.is_finalized:
                from pex.pex_builder import PEXBuilder

                isolated_pip_builder = PEXBuilder(path=chroot.work_dir)
                isolated_pip_builder.info.venv = True
                for dist_location in third_party.expose(["pip", "setuptools", "wheel"]):
                    isolated_pip_builder.add_dist_location(dist=dist_location)
                with named_temporary_file(prefix="", suffix=".py", mode="w") as fp:
                    fp.write(
                        dedent(
                            """\
                            import os
                            import runpy

                            patched_markers_file = os.environ.pop(
                                {patched_markers_env_var_name!r}, None
                            )
                            if patched_markers_file:
                                def patch_markers():
                                    import json

                                    from pip._vendor.packaging import markers

                                    with open(patched_markers_file) as fp:
                                        patched_markers = json.load(fp)

                                    markers.default_environment = patched_markers.copy

                                patch_markers()
                                del patch_markers

                            runpy.run_module(mod_name="pip", run_name="__main__", alter_sys=True)
                            """.format(
                                patched_markers_env_var_name=cls._PATCHED_MARKERS_FILE_ENV_VAR_NAME
                            )
                        )
                    )
                    fp.close()
                    isolated_pip_builder.set_executable(fp.name, "__pex_patched_pip__.py")
                isolated_pip_builder.freeze()
        pex_info = PexInfo.from_pex(pip_pex_path)
        pex_info.add_interpreter_constraint(str(pip_interpreter.identity.requirement))
        return cls(ensure_venv(PEX(pip_pex_path, interpreter=pip_interpreter, pex_info=pex_info)))

    def __init__(self, pip_pex_path):
        # type: (str) -> None
        self._pip_pex_path = pip_pex_path  # type: str

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
            stdout = popen_kwargs.pop("stdout", sys.stderr.fileno())

            args = [self._pip_pex_path] + command
            return args, subprocess.Popen(args=args, env=env, stdout=stdout, **popen_kwargs)

    def _spawn_pip_isolated_job(
        self,
        args,  # type: Iterable[str]
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
        cache=None,  # type: Optional[str]
        interpreter=None,  # type: Optional[PythonInterpreter]
        pip_verbosity=0,  # type: int
        finalizer=None,  # type: Optional[Callable[[], None]]
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
        target=None,  # type: Optional[DistributionTarget]
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
        cache=None,  # type: Optional[str]
        build=True,  # type: bool
        use_wheel=True,  # type: bool
    ):
        # type: (...) -> Job
        target = target or DistributionTarget.current()

        platform, manylinux = target.get_platform()
        if not use_wheel:
            if not build:
                raise ValueError(
                    "Cannot both ignore wheels (use_wheel=False) and refrain from building "
                    "distributions (build=False)."
                )
            elif target.is_platform:
                raise ValueError(
                    "Cannot ignore wheels (use_wheel=False) when resolving for a platform: "
                    "{}".format(platform)
                )

        download_cmd = ["download", "--dest", download_dir]
        if target.is_platform:
            # We're either resolving for a different host / platform or a different interpreter for
            # the current platform that we have no access to; so we need to let pip know and not
            # otherwise pickup platform info from the interpreter we execute pip with.
            download_cmd.extend(
                self._iter_platform_args(
                    platform=platform.platform,
                    impl=platform.impl,
                    version=platform.version,
                    abi=platform.abi,
                    manylinux=manylinux,
                )
            )

        if target.is_platform or not build:
            download_cmd.extend(["--only-binary", ":all:"])

        if not use_wheel:
            download_cmd.extend(["--no-binary", ":all:"])

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

        extra_env = None
        log_analyzers = []  # type: List[_LogAnalyzer]

        # Pip evaluates environment markers in the context of the ambient interpreter instead of
        # failing when encountering them, ignoring them or doing what we do here: evaluate those
        # environment markers positively identified by the platform quadruple and failing for those
        # we cannot know.
        if target.is_platform:
            env_markers_dir = safe_mkdtemp()
            platform, _ = target.get_platform()
            patched_environment = platform.marker_environment(
                # We want to fail a resolve when it needs to evaluate environment markers we can't
                # calculate given just the platform information.
                default_unknown=False
            )
            with open(
                os.path.join(env_markers_dir, "env_markers.{}.json".format(platform)), "w"
            ) as fp:
                json.dump(patched_environment, fp)
            extra_env = {self._PATCHED_MARKERS_FILE_ENV_VAR_NAME: fp.name}
            log_analyzers.append(_Issue10050Analyzer(platform=platform))
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
        if log_analyzers:
            log = os.path.join(safe_mkdtemp(), "pip.log")
            download_cmd = ["--log", log] + download_cmd

        command, process = self._spawn_pip_isolated(
            download_cmd,
            package_index_configuration=package_index_configuration,
            cache=cache,
            interpreter=target.get_interpreter(),
            extra_env=extra_env,
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
        verify=True,  # type: bool
    ):
        # type: (...) -> Job
        wheel_cmd = ["wheel", "--no-deps", "--wheel-dir", wheel_dir]
        if not verify:
            wheel_cmd.append("--no-verify")
        wheel_cmd.extend(distributions)

        return self._spawn_pip_isolated_job(
            wheel_cmd,
            # If the build leverages PEP-518 it will need to resolve build requirements.
            package_index_configuration=package_index_configuration,
            cache=cache,
            interpreter=interpreter,
        )

    @classmethod
    def _fixup_install(
        cls,
        dist,  # type: str
        install_dir,  # type: str
    ):
        # type: (...) -> None
        modified_scripts = list(cls._fixup_scripts(install_dir))
        cls._fixup_record(dist, install_dir, modified_scripts=modified_scripts)

    @staticmethod
    def _fixup_record(
        dist,  # type: str
        install_dir,  # type: str
        modified_scripts=None,  # type: Optional[Iterable[str]]
    ):
        # type: (...) -> None

        # The dist-info metadata directory is named as specifed in:
        #   https://www.python.org/dev/peps/pep-0427/
        #   https://packaging.python.org/specifications/recording-installed-packages/#the-dist-info-directory
        project_name_and_version = dist_metadata.project_name_and_version(
            dist
        ) or ProjectNameAndVersion.from_filename(dist)

        # The `direct_url.json` file is both mandatory for Pip to install and non-hermetic for
        # Pex's purpose, since it contains the absolute local filesystem path to any local wheel
        # file Pex installs via Pip. We remove the file and its entry in RECORD so that PEX files
        # are bytewise reproducible. The absence of the direct_url.json file only affects Pex venvs
        # where further mutation by PEP-compatible packaging tooling (e.g.: Pip) may be hindered.
        # In particular, `pip freeze` for any distributions provided by local projects or archives
        # will produce unuseful entries for those distributions.
        #
        # See:
        #   https://www.python.org/dev/peps/pep-0610/
        #   https://packaging.python.org/specifications/direct-url/#specification
        listing = [
            os.path.relpath(os.path.join(root, f), install_dir)
            for root, _, files in os.walk(install_dir)
            for f in files
        ]
        record_relpath = dist_metadata.find_dist_info_file(
            project_name=project_name_and_version.project_name,
            version=project_name_and_version.version,
            filename="RECORD",
            listing=listing,
        )
        if not record_relpath:
            return

        exclude_relpaths = []

        record_abspath = os.path.join(install_dir, record_relpath)
        dist_info_dir = os.path.dirname(record_abspath)

        direct_url_abspath = os.path.join(dist_info_dir, "direct_url.json")
        direct_url_relpath = os.path.relpath(direct_url_abspath, install_dir)
        if os.path.exists(direct_url_abspath):
            with open(direct_url_abspath) as fp:
                if urlparse.urlparse(json.load(fp)["url"]).scheme == "file":
                    exclude_relpaths.append(os.path.relpath(direct_url_abspath, install_dir))
                    os.unlink(direct_url_abspath)

        to_rehash = {}
        if modified_scripts:
            for modified_script in modified_scripts:
                # N.B.: Pip installs wheels with RECORD entries like `../../bin/script` even when it's
                # called in `--target <dir>` mode which installs the script in `bin/script`.
                record_relpath = os.path.join(os.pardir, os.pardir, modified_script)
                modified_script_abspath = os.path.join(install_dir, modified_script)
                to_rehash[record_relpath] = modified_script_abspath

        # The RECORD is a csv file with the path to each installed file in the 1st column.
        # See: https://www.python.org/dev/peps/pep-0376/#record
        with closing(fileinput.input(files=[record_abspath], inplace=True, mode="rU")) as record_fi:
            csv_writer = None  # type: Optional[CSVWriter]
            for path, existing_hash, existing_size in csv.reader(
                record_fi, delimiter=",", quotechar='"'
            ):
                if csv_writer is None:
                    # N.B.: The raw input lines include a newline that varies between '\r\n' and
                    # '\n' when the wheel was built from an sdist by Pip depending on whether the
                    # interpreter used was Python 2 or Python 3 respectively. As such, we normalize
                    # all RECORD files to use '\n' regardless of interpreter.
                    csv_writer = cast(
                        "CSVWriter",
                        csv.writer(sys.stdout, delimiter=",", quotechar='"', lineterminator="\n"),
                    )

                abspath_to_rehash = to_rehash.pop(path, None)
                if existing_hash and abspath_to_rehash is not None:
                    algorithm = existing_hash.split("=")[0]
                    hasher = hashlib.new(algorithm)
                    with open(abspath_to_rehash, "rb") as rehash_fp:
                        CacheHelper.update_hash(rehash_fp, digest=hasher)

                    fingerprint = base64.urlsafe_b64encode(hasher.digest()).decode("ascii")
                    de_padded, pad, rest = fingerprint.rpartition("=")
                    new_hash = str(de_padded if pad and not rest else fingerprint)
                    new_size = os.stat(abspath_to_rehash).st_size
                    csv_writer.writerow((path, new_hash, new_size))
                elif path != direct_url_relpath:
                    csv_writer.writerow((path, existing_hash, existing_size))

    @staticmethod
    def _fixup_scripts(
        install_dir,  # type: str
    ):
        # type: (...) -> Iterator[str]
        bin_dir = os.path.join(install_dir, "bin")
        if not os.path.isdir(bin_dir):
            return

        scripts = []
        for script_name in os.listdir(bin_dir):
            script_path = os.path.join(bin_dir, script_name)
            if DistributionScript.is_python_script(script_path):
                scripts.append(script_path)
        if not scripts:
            return

        with closing(fileinput.input(files=scripts, inplace=True)) as script_fi:
            for line in script_fi:
                if script_fi.isfirstline():
                    # Ensure python shebangs are reproducible. The only place these can be used is
                    # in venv mode PEXes where the `#!python` placeholder shebang will be re-written
                    # to use the venv's python interpreter.
                    print("#!python")
                    yield os.path.relpath(script_fi.filename(), install_dir)
                else:
                    # N.B.: These lines include the newline already.
                    sys.stdout.write(line)

    def spawn_install_wheel(
        self,
        wheel,  # type: str
        install_dir,  # type: str
        compile=False,  # type: bool
        cache=None,  # type: Optional[str]
        target=None,  # type: Optional[DistributionTarget]
    ):
        # type: (...) -> Job
        target = target or DistributionTarget.current()

        install_cmd = [
            "install",
            "--no-deps",
            "--no-index",
            "--only-binary",
            ":all:",
            "--target",
            install_dir,
        ]

        interpreter = target.get_interpreter()
        if target.is_foreign:
            if compile:
                raise ValueError(
                    "Cannot compile bytecode for {} using {} because the wheel has a foreign "
                    "platform.".format(wheel, interpreter)
                )

            # We're installing a wheel for a foreign platform. This is just an unpacking operation
            # though; so we don't actually need to perform it with a target platform compatible
            # interpreter (except for scripts - see below).
            install_cmd.append("--ignore-requires-python")

            # The new Pip 2020-resolver rightly refuses to install foreign wheels since they may
            # contain python scripts that request a shebang re-write (see
            # https://docs.python.org/3/distutils/setupscript.html#installing-scripts) in which case
            # Pip would not be able to perform the re-write, leaving an un-runnable script. Since we
            # only expose scripts via the Pex Venv tool and that tool re-writes shebangs anyhow, we
            # trick Pip here by re-naming the wheel to look compatible with the current interpreter.

            # Wheel filename format: https://www.python.org/dev/peps/pep-0427/#file-name-convention
            # `{distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl`
            wheel_basename = os.path.basename(wheel)
            wheel_name, extension = os.path.splitext(wheel_basename)
            prefix, python_tag, abi_tag, platform_tag = wheel_name.rsplit("-", 3)
            target_tags = PythonInterpreter.get().identity.supported_tags[0]
            renamed_wheel = os.path.join(
                os.path.dirname(wheel),
                "{prefix}-{target_tags}{extension}".format(
                    prefix=prefix, target_tags=target_tags, extension=extension
                ),
            )
            os.symlink(wheel_basename, renamed_wheel)
            TRACER.log(
                "Re-named {} to {} to perform foreign wheel install.".format(wheel, renamed_wheel)
            )
            wheel = renamed_wheel

        install_cmd.append("--compile" if compile else "--no-compile")
        install_cmd.append(wheel)

        return self._spawn_pip_isolated_job(
            args=install_cmd,
            cache=cache,
            interpreter=interpreter,
            finalizer=functools.partial(self._fixup_install, dist=wheel, install_dir=install_dir),
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
