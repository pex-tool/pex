# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re
import shutil
import subprocess
from collections import OrderedDict
from subprocess import CalledProcessError

from pex import toml
from pex.atomic_directory import atomic_directory
from pex.cache.dirs import CacheDir
from pex.common import pluralize, safe_mkdtemp, safe_open
from pex.compatibility import shlex_quote
from pex.dist_metadata import NamedEntryPoint, parse_entry_point
from pex.enum import Enum
from pex.exceptions import reportable_unexpected_error_msg
from pex.executables import chmod_plus_x
from pex.fetcher import URLFetcher
from pex.hashing import Sha256
from pex.os import is_exe
from pex.pep_440 import Version
from pex.pex import PEX
from pex.result import Error, try_
from pex.scie.model import (
    File,
    InterpreterDistribution,
    PlatformNamingStyle,
    Provider,
    ScieConfiguration,
    ScieInfo,
    ScieStyle,
    Url,
)
from pex.sysconfig import SysPlatform
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.packaging.version import InvalidVersion
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper
from pex.variables import ENV, Variables

if TYPE_CHECKING:
    from typing import Any, Dict, Iterator, List, Optional, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Manifest(object):
    interpreter = attr.ib()  # type: InterpreterDistribution
    path = attr.ib()  # type: str

    def binary_name(self, binary_name):
        # type: (str) -> str
        return self.interpreter.platform.binary_name(binary_name)

    def qualified_binary_name(self, binary_name):
        # type: (str) -> str
        return self.interpreter.platform.qualified_binary_name(binary_name)


SCIENCE_RELEASES_URL = "https://github.com/a-scie/lift/releases"
MIN_SCIENCE_VERSION = Version("0.12.4")
SCIENCE_REQUIREMENT = SpecifierSet("~={min_version}".format(min_version=MIN_SCIENCE_VERSION))


def _science_binary_url(suffix=""):
    # type: (str) -> str
    return "{science_releases_url}/download/v{version}/{binary}{suffix}".format(
        science_releases_url=SCIENCE_RELEASES_URL,
        version=MIN_SCIENCE_VERSION.raw,
        binary=SysPlatform.CURRENT.qualified_binary_name("science-fat"),
        suffix=suffix,
    )


PTEX_VERSION = "1.6.1"
SCIE_JUMP_VERSION = "1.7.0"


class Filenames(Enum["Filenames.Value"]):
    class Filename(Enum.Value):
        def __init__(self, value):
            # type: (str) -> None
            Enum.Value.__init__(self, value)
            self.name = value

        @property
        def placeholder(self):
            # type: () -> str
            return "{{{name}}}".format(name=self.name)

    PTEX = Filename("ptex")
    PEX = Filename("pex")
    CONFIGURE_BINDING = Filename("configure-binding.py")


Filenames.seal()


def create_manifests(
    configuration,  # type: ScieConfiguration
    name,  # type: str
    pex,  # type: PEX
    use_platform_suffix=None,  # type: Optional[bool]
):
    # type: (...) -> Iterator[Manifest]

    pex_info = pex.pex_info(include_env_overrides=False)
    if pex_info.pex_hash is None:
        raise ValueError(
            reportable_unexpected_error_msg(
                "PEX at {pex} is unexpectedly missing a `pex_hash` in its PEX-INFO.", pex=pex.path()
            )
        )
    pex_hash = pex_info.pex_hash

    def create_commands(platform):
        # type: (SysPlatform.Value) -> Iterator[Dict[str, Any]]
        entrypoints = configuration.options.busybox_entrypoints
        if entrypoints:
            pex_entry_point = parse_entry_point(pex_info.entry_point)

            def default_env(named_entry_point):
                # type: (...) -> Dict[str, str]
                return (
                    pex_info.inject_env if named_entry_point.entry_point == pex_entry_point else {}
                )

            def args(
                named_entry_point,  # type: NamedEntryPoint
                *args  # type: str
            ):
                # type: (...) -> List[str]
                all_args = (
                    list(pex_info.inject_python_args)
                    if named_entry_point.entry_point == pex_entry_point
                    else []
                )
                all_args.extend(args)
                if named_entry_point.entry_point == pex_entry_point:
                    all_args.extend(pex_info.inject_args)
                return all_args

            def create_cmd(named_entry_point):
                # type: (NamedEntryPoint) -> Dict[str, Any]

                if (
                    configuration.options.busybox_pex_entrypoint_env_passthrough
                    and named_entry_point.entry_point == pex_entry_point
                ):
                    env = {
                        "default": default_env(named_entry_point),
                        "remove_exact": ["PEX_VENV"],
                        "replace": {
                            "__PEX_EXE__": "{scie}",
                            "__PEX_ENTRY_POINT__": "{scie.bindings.configure:PEX}",
                        },
                    }
                else:
                    env = {
                        "default": default_env(named_entry_point),
                        "remove_exact": ["PEX_INTERPRETER", "PEX_SCRIPT", "PEX_VENV"],
                        "replace": {
                            "__PEX_EXE__": "{scie}",
                            "__PEX_ENTRY_POINT__": "{scie.bindings.configure:PEX}",
                            "PEX_MODULE": str(named_entry_point.entry_point),
                        },
                    }
                return {
                    "name": named_entry_point.name,
                    "env": env,
                    "exe": "{scie.bindings.configure:PYTHON}",
                    "args": args(named_entry_point, "{scie.bindings.configure:PEX}"),
                }

            if pex_info.venv and not configuration.options.busybox_pex_entrypoint_env_passthrough:
                # N.B.: Executing the console script directly instead of bouncing through the PEX
                # __main__.py using PEX_SCRIPT saves ~10ms of re-exec overhead in informal testing; so
                # it's worth specializing here.
                for named_entry_point in entrypoints.console_scripts_manifest.collect(pex):
                    yield {
                        "name": named_entry_point.name,
                        "env": {
                            "default": default_env(named_entry_point),
                            "remove_exact": [
                                "PEX_INTERPRETER",
                                "PEX_MODULE",
                                "PEX_SCRIPT",
                                "PEX_VENV",
                            ],
                        },
                        "exe": "{scie.bindings.configure:PYTHON}",
                        "args": args(
                            named_entry_point,
                            "{scie.bindings.configure:VENV_BIN_DIR_PLUS_SEP}"
                            + platform.binary_name(named_entry_point.name),
                        ),
                    }
            else:
                for named_entry_point in entrypoints.console_scripts_manifest.collect(pex):
                    yield create_cmd(named_entry_point)
            for named_entry_point in entrypoints.ad_hoc_entry_points:
                yield create_cmd(named_entry_point)
        else:
            yield {
                "env": {
                    "remove_exact": ["PEX_VENV"],
                    "replace": {
                        "__PEX_EXE__": "{scie}",
                        "__PEX_ENTRY_POINT__": "{scie.bindings.configure:PEX}",
                    },
                },
                "exe": "{scie.bindings.configure:PYTHON}",
                "args": ["{scie.bindings.configure:PEX}"],
            }

    # Try to give the PEX the extracted filename expected by the user. This should work in almost
    # all cases save for the Pex PEX.
    pex_name = os.path.basename(pex.path())
    if pex_name not in frozenset(filename.value for filename in Filenames.values()):
        pex_key = Filenames.PEX.name  # type: Optional[str]
    else:
        pex_name = Filenames.PEX.name
        pex_key = None

    scie_jump_config = {"version": SCIE_JUMP_VERSION}
    if configuration.options.assets_base_url:
        scie_jump_config["base_url"] = "/".join((configuration.options.assets_base_url, "jump"))

    lift_template = {
        "name": name,
        "scie_jump": scie_jump_config,
        "files": [
            {"name": Filenames.CONFIGURE_BINDING.name},
            dict(name=pex_name, is_executable=True, **({"key": pex_key} if pex_key else {})),
        ],
    }  # type: Dict[str, Any]

    if configuration.options.style is ScieStyle.LAZY:
        ptex_config = lift_template["ptex"] = {
            "id": Filenames.PTEX.name,
            "version": PTEX_VERSION,
            "argv1": "{scie.env.PEX_BOOTSTRAP_URLS={scie.lift}}",
        }
        if configuration.options.assets_base_url:
            ptex_config["base_url"] = "/".join((configuration.options.assets_base_url, "ptex"))

    configure_binding = {
        "env": {
            "remove_exact": ["PATH"],
            "remove_re": ["PEX_.*", "PYTHON.*"],
            "replace": {
                "PEX_INTERPRETER": "1",
                # We can get a warning about too-long script shebangs, but this is not
                # relevant since we above run the PEX via python and not via shebang.
                "PEX_EMIT_WARNINGS": "0",
            },
        },
        "name": "configure",
        "exe": "#{python-distribution:python}",
    }

    configure_binding_args = [Filenames.PEX.placeholder, Filenames.CONFIGURE_BINDING.placeholder]
    for interpreter in configuration.interpreters:
        lift = lift_template.copy()

        if configuration.options.base:
            lift["base"] = configuration.options.base
        elif pex_info.pex_root:
            lift["base"] = CacheDir.SCIES.path(
                "base", os=interpreter.platform.os, pex_root=pex_info.pex_root
            )

        manifest_path = os.path.join(
            safe_mkdtemp(),
            interpreter.platform.qualified_file_name("{name}-lift.toml".format(name=name)),
        )

        interpreter_config = {
            "id": "python-distribution",
            "provider": interpreter.provider.value,
            "version": interpreter.version_str,
            "lazy": configuration.options.style is ScieStyle.LAZY,
        }
        if interpreter.release:
            interpreter_config["release"] = interpreter.release
        if configuration.options.assets_base_url:
            interpreter_config["base_url"] = "/".join(
                (configuration.options.assets_base_url, "providers", str(interpreter.provider))
            )
        if Provider.PythonBuildStandalone is interpreter.provider:
            interpreter_config.update(
                flavor=(
                    "install_only_stripped"
                    if configuration.options.pbs_stripped
                    else "install_only"
                )
            )

        extra_configure_binding_args = []  # type: List[str]
        if pex_info.venv:
            extra_configure_binding_args.extend(
                ("--venv-bin-dir", interpreter.platform.venv_bin_dir)
            )
        extra_configure_binding_args.append(pex_hash)

        if use_platform_suffix is True or (
            use_platform_suffix is None and interpreter.platform is not SysPlatform.CURRENT
        ):
            lift["platforms"] = [interpreter.platform.value]

        with safe_open(manifest_path, "wb") as fp:
            toml.dump(
                {
                    "lift": dict(
                        lift,
                        interpreters=[interpreter_config],
                        commands=list(create_commands(interpreter.platform)),
                        bindings=[
                            dict(
                                configure_binding,
                                args=configure_binding_args + extra_configure_binding_args,
                            )
                        ],
                    )
                },
                fp,
            )
        yield Manifest(interpreter=interpreter, path=manifest_path)


def _science_dir(
    env,  # type: Variables
    *components  # type: str
):
    # type: (...) -> str
    return CacheDir.SCIES.path("science", MIN_SCIENCE_VERSION.raw, *components, pex_root=env)


def _science_binary_names():
    # type: () -> Iterator[str]
    yield SysPlatform.CURRENT.binary_name("science-fat")
    yield SysPlatform.CURRENT.qualified_binary_name("science-fat")
    yield SysPlatform.CURRENT.binary_name("science")
    yield SysPlatform.CURRENT.qualified_binary_name("science")


def _is_compatible_science_binary(
    binary,  # type: str
    source=None,  # type: Optional[str]
):
    # type: (...) -> Union[Version, Error]
    try:
        version = Version(
            subprocess.check_output(args=[binary, "--version"]).decode("utf-8").strip()
        )
    except (CalledProcessError, InvalidVersion) as e:
        return Error(
            "Failed to determine --version of science binary at {source}: {err}".format(
                source=source or binary, err=e
            )
        )
    else:
        if version.raw in SCIENCE_REQUIREMENT:
            return version
        return Error(
            "The science binary at {source} is version {version} which does not match Pex's "
            "science requirement of {science_requirement}.".format(
                source=source or binary,
                version=version.raw,
                science_requirement=SCIENCE_REQUIREMENT,
            )
        )


def _path_science():
    # type: () -> Optional[str]
    for path_element in os.environ.get("PATH", os.defpath).split(os.pathsep):
        for binary in (
            os.path.join(path_element, binary_name) for binary_name in _science_binary_names()
        ):
            if not is_exe(binary):
                continue
            if isinstance(_is_compatible_science_binary(binary), Error):
                continue
            return binary
    return None


def ensure_science(
    url_fetcher=None,  # type: Optional[URLFetcher]
    science_binary=None,  # type: Optional[Union[File, Url]]
    env=ENV,  # type: Variables
):
    # type: (...) -> str

    if isinstance(science_binary, File):
        if not is_exe(science_binary):
            raise ValueError(
                "The --scie-science-binary at {source} is not an executable.".format(
                    source=science_binary
                )
            )
        custom_science_binary_version = try_(_is_compatible_science_binary(science_binary))
        TRACER.log(
            "Using custom science binary from {source} with version "
            "{version}.".format(source=science_binary, version=custom_science_binary_version.raw)
        )
        return science_binary

    target_dir = _science_dir(env, "bin")
    with atomic_directory(target_dir=target_dir) as atomic_dir:
        if not atomic_dir.is_finalized():
            target_science = os.path.join(atomic_dir.work_dir, "science")
            if not science_binary:
                path_science = _path_science()
                if path_science:
                    shutil.copy(path_science, target_science)
            if not os.path.exists(target_science):
                fetcher = url_fetcher or URLFetcher()
                url = science_binary or _science_binary_url()
                TRACER.log("Fetching science binary from {url}...".format(url=url))
                with open(target_science, "wb") as write_fp, fetcher.get_body_stream(
                    science_binary or _science_binary_url()
                ) as read_fp:
                    shutil.copyfileobj(read_fp, write_fp)
                chmod_plus_x(target_science)

                if science_binary:
                    custom_science_binary_version = try_(
                        _is_compatible_science_binary(target_science, source=science_binary)
                    )
                    TRACER.log(
                        "Using custom science binary from {source} with version "
                        "{version}.".format(
                            source=science_binary, version=custom_science_binary_version.raw
                        )
                    )
                else:
                    # Since we used the canonical GitHub Releases URL, we know a checksum file is
                    # available we can use to verify.
                    science_sha256_url = _science_binary_url(".sha256")
                    with fetcher.get_body_stream(science_sha256_url) as fp:
                        expected_sha256, _, _ = fp.read().decode("utf-8").partition(" ")
                    actual_sha256 = CacheHelper.hash(target_science, hasher=Sha256)
                    if expected_sha256 != actual_sha256:
                        raise ValueError(
                            "The science binary downloaded from {science_binary_url} does not "
                            "match the expected SHA-256 fingerprint recorded in "
                            "{science_sha256_url}.\n"
                            "Expected {expected_sha256} but found {actual_sha256}.".format(
                                science_binary_url=science_binary,
                                science_sha256_url=science_sha256_url,
                                expected_sha256=expected_sha256,
                                actual_sha256=actual_sha256,
                            )
                        )
    return os.path.join(target_dir, "science")


class ScienceError(Exception):
    """Indicates an error executing science."""


def build(
    configuration,  # type: ScieConfiguration
    pex_file,  # type: str
    url_fetcher=None,  # type: Optional[URLFetcher]
    env=ENV,  # type: Variables
):
    # type: (...) -> Iterator[ScieInfo]

    science = ensure_science(
        url_fetcher=url_fetcher,
        science_binary=configuration.options.science_binary,
        env=env,
    )
    name = re.sub(r"\.pex$", "", os.path.basename(pex_file), flags=re.IGNORECASE)
    pex = PEX(pex_file)

    naming_style = configuration.options.naming_style or PlatformNamingStyle.DYNAMIC
    use_platform_suffix = None  # type: Optional[bool]
    if PlatformNamingStyle.FILE_SUFFIX is naming_style:
        use_platform_suffix = True
    elif PlatformNamingStyle.PARENT_DIR is naming_style:
        use_platform_suffix = False
    elif len(configuration.interpreters) > 1:
        use_platform_suffix = True

    errors = OrderedDict()  # type: OrderedDict[Manifest, str]
    for manifest in create_manifests(configuration, name, pex, use_platform_suffix):
        args = [science, "--cache-dir", _science_dir(env, "cache")]
        if env.PEX_VERBOSE:
            args.append("-{verbosity}".format(verbosity="v" * env.PEX_VERBOSE))
        dest_dir = os.path.dirname(os.path.abspath(pex_file))
        if PlatformNamingStyle.PARENT_DIR is naming_style:
            dest_dir = os.path.join(dest_dir, manifest.interpreter.platform.value)
        args.extend(
            [
                "lift",
                "--file",
                "{name}={pex_file}".format(name=Filenames.PEX.name, pex_file=pex_file),
                "--file",
                "{name}={configure_binding}".format(
                    name=Filenames.CONFIGURE_BINDING.name,
                    configure_binding=os.path.join(
                        os.path.dirname(__file__), "configure-binding.py"
                    ),
                ),
                "build",
                "--dest-dir",
                dest_dir,
            ]
        )
        if use_platform_suffix is not None:
            args.append(
                "--use-platform-suffix" if use_platform_suffix else "--no-use-platform-suffix"
            )
        for hash_algorithm in configuration.options.hash_algorithms:
            args.extend(["--hash", hash_algorithm])
        args.append(manifest.path)

        environ = os.environ.copy()
        if url_fetcher:
            environ.update(url_fetcher.network_env())

        with open(os.devnull, "wb") as devnull:
            process = subprocess.Popen(
                args=args, env=environ, stdout=devnull, stderr=subprocess.PIPE
            )
            _, stderr = process.communicate()
            if process.returncode != 0:
                saved_manifest = os.path.relpath(
                    os.path.join(dest_dir, os.path.basename(manifest.path))
                )
                shutil.copy(manifest.path, saved_manifest)
                errors[manifest] = (
                    "Command `{command}` failed with exit code {exit_code} (saved lift manifest to "
                    "{saved_manifest} for inspection):\n{stderr}"
                ).format(
                    command=" ".join(shlex_quote(arg) for arg in args[:-1] + [saved_manifest]),
                    exit_code=process.returncode,
                    saved_manifest=saved_manifest,
                    stderr=stderr.decode("utf-8").strip(),
                )
            else:
                yield ScieInfo(
                    style=configuration.options.style,
                    interpreter=manifest.interpreter,
                    file=os.path.join(
                        dest_dir,
                        (
                            manifest.qualified_binary_name(name)
                            if use_platform_suffix
                            else manifest.binary_name(name)
                        ),
                    ),
                )

    if errors:
        raise ScienceError(
            "Failed to build {count} {scies}:\n\n{errors}".format(
                count=len(errors),
                scies=pluralize(errors, "scie"),
                errors="\n\n".join(
                    "{index}. For {python_description}: {err}".format(
                        index=index,
                        python_description=manifest.interpreter.render_description(),
                        err=err,
                    )
                    for index, (manifest, err) in enumerate(errors.items(), start=1)
                ),
            )
        )
