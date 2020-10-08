# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
from collections import deque
from textwrap import dedent

from pex import third_party
from pex.common import atomic_directory
from pex.compatibility import urlparse
from pex.distribution_target import DistributionTarget
from pex.interpreter import PythonInterpreter
from pex.jobs import Job
from pex.network_configuration import NetworkConfiguration
from pex.third_party import isolated
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import Iterable, Iterator, List, Mapping, Optional, Tuple


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

        network_configuration = network_configuration or NetworkConfiguration.create()

        # N.B.: Pip sends `Cache-Control: max-age=0` by default which turns of HTTP caching as per
        # the spec:
        yield "--header"
        yield "Cache-Control:max-age={}".format(network_configuration.cache_ttl)

        for header in network_configuration.headers:
            yield "--header"
            yield header

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
            yield "PIP_CLIENT_CERT", network_configuration.cert

    @classmethod
    def create(
        cls,
        indexes=None,  # type: Optional[List[str]]
        find_links=None,  # type: Optional[List[str]]
        network_configuration=None,  # type: Optional[NetworkConfiguration]
    ):
        # type: (...) -> PackageIndexConfiguration
        network_configuration = network_configuration or NetworkConfiguration.create()

        # We must pass `--client-cert` via PIP_CLIENT_CERT to work around
        # https://github.com/pypa/pip/issues/5502. We can only do this by breaking Pip `--isolated`
        # mode.
        isolated = not network_configuration.client_cert

        return cls(
            args=cls._calculate_args(
                indexes=indexes, find_links=find_links, network_configuration=network_configuration
            ),
            env=cls._calculate_env(network_configuration=network_configuration, isolated=isolated),
            isolated=isolated,
        )

    def __init__(
        self,
        args,  # type: Iterable[str]
        env,  # type: Iterable[Tuple[str, str]]
        isolated,  # type: bool
    ):
        # type: (...) -> None
        self.args = tuple(args)  # type: Iterable[str]
        self.env = dict(env)  # type: Mapping[str, str]
        self.isolated = isolated  # type: bool


class Pip(object):
    @classmethod
    def create(cls, path):
        # type: (str) -> Pip
        """Creates a pip tool with PEX isolation at path.

        :param path: The path to build the pip tool pex at.
        """
        pip_pex_path = os.path.join(path, isolated().pex_hash)
        with atomic_directory(pip_pex_path, exclusive=True) as chroot:
            if chroot is not None:
                from pex.pex_builder import PEXBuilder

                isolated_pip_builder = PEXBuilder(path=chroot)
                pythonpath = third_party.expose(["pip", "setuptools", "wheel"])
                isolated_pip_environment = third_party.pkg_resources.Environment(
                    search_path=pythonpath
                )
                for dist_name in isolated_pip_environment:
                    for dist in isolated_pip_environment[dist_name]:
                        isolated_pip_builder.add_dist_location(dist=dist.location)
                with open(os.path.join(isolated_pip_builder.path(), "run_pip.py"), "w") as fp:
                    fp.write(
                        dedent(
                            """\
                            import os
                            import runpy
                            import sys
                            
                            
                            # Propagate un-vendored setuptools to pip for any legacy setup.py builds it needs to
                            # perform.
                            os.environ['__PEX_UNVENDORED__'] = '1'
                            os.environ['PYTHONPATH'] = os.pathsep.join(sys.path)
                            
                            runpy.run_module('pip', run_name='__main__')
                            """
                        )
                    )
                isolated_pip_builder.set_executable(fp.name)
                isolated_pip_builder.freeze()

        return cls(pip_pex_path)

    def __init__(self, pip_pex_path):
        # type: (str) -> None
        self._pip_pex_path = pip_pex_path  # type: str

    def _spawn_pip_isolated(
        self,
        args,  # type: Iterable[str]
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
        cache=None,  # type: Optional[str]
        interpreter=None,  # type: Optional[PythonInterpreter]
    ):
        # type: (...) -> Job
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
        if not package_index_configuration or package_index_configuration.isolated:
            # Don't read PIP_ environment variables or pip configuration files like
            # `~/.config/pip/pip.conf`.
            pip_args.append("--isolated")

        # The max pip verbosity is -vvv and for pex it's -vvvvvvvvv; so we scale down by a factor
        # of 3.
        pip_verbosity = ENV.PEX_VERBOSE // 3
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

        env = package_index_configuration.env if package_index_configuration else {}
        with ENV.strip().patch(
            PEX_ROOT=cache or ENV.PEX_ROOT, PEX_VERBOSE=str(ENV.PEX_VERBOSE), **env
        ) as env:
            # Guard against API calls from environment with ambient PYTHONPATH preventing pip PEX
            # bootstrapping. See: https://github.com/pantsbuild/pex/issues/892
            pythonpath = env.pop("PYTHONPATH", None)
            if pythonpath:
                TRACER.log(
                    "Scrubbed PYTHONPATH={} from the pip PEX environment.".format(pythonpath), V=3
                )

            from pex.pex import PEX

            pip = PEX(pex=self._pip_pex_path, interpreter=interpreter)
            return Job(
                command=pip.cmdline(command), process=pip.run(args=command, env=env, blocking=False)
            )

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
        manylinux=None,  # type: Optional[str]
        use_wheel=True,  # type: bool
    ):
        # type: (...) -> Job
        target = target or DistributionTarget.current()

        platform = target.get_platform()
        if not use_wheel:
            if not build:
                raise ValueError(
                    "Cannot both ignore wheels (use_wheel=False) and refrain from building "
                    "distributions (build=False)."
                )
            elif target.is_foreign:
                raise ValueError(
                    "Cannot ignore wheels (use_wheel=False) when resolving for a foreign "
                    "platform: {}".format(platform)
                )

        download_cmd = ["download", "--dest", download_dir]
        if target.is_foreign:
            # We're either resolving for a different host / platform or a different interpreter for
            # the current platform that we have no access to; so we need to let pip know and not
            # otherwise pickup platform info from the interpreter we execute pip with.
            if manylinux and platform.platform.startswith("linux"):
                download_cmd.extend(
                    ["--platform", platform.platform.replace("linux", manylinux, 1)]
                )
            download_cmd.extend(["--platform", platform.platform])
            download_cmd.extend(["--implementation", platform.impl])
            download_cmd.extend(["--python-version", platform.version])
            download_cmd.extend(["--abi", platform.abi])

        if target.is_foreign or not build:
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

        return self._spawn_pip_isolated(
            download_cmd,
            package_index_configuration=package_index_configuration,
            cache=cache,
            interpreter=target.get_interpreter(),
        )

    def spawn_build_wheels(
        self,
        distributions,  # type: Iterable[str]
        wheel_dir,  # type: str
        interpreter=None,  # type: Optional[PythonInterpreter]
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
        cache=None,  # type: Optional[str]
    ):
        # type: (...) -> Job
        wheel_cmd = ["wheel", "--no-deps", "--wheel-dir", wheel_dir]
        wheel_cmd.extend(distributions)

        return self._spawn_pip_isolated(
            wheel_cmd,
            # If the build leverages PEP-518 it will need to resolve build requirements.
            package_index_configuration=package_index_configuration,
            cache=cache,
            interpreter=interpreter,
        )

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
            # interpreter.
            install_cmd.append("--ignore-requires-python")

        install_cmd.append("--compile" if compile else "--no-compile")
        install_cmd.append(wheel)
        return self._spawn_pip_isolated(install_cmd, cache=cache, interpreter=interpreter)


_PIP = None


def get_pip():
    # type: () -> Pip
    """Returns a lazily instantiated global Pip object that is safe for un-coordinated use."""
    global _PIP
    if _PIP is None:
        _PIP = Pip.create(path=os.path.join(ENV.PEX_ROOT, "pip.pex"))
    return _PIP
