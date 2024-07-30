# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re
import shutil
import subprocess
from collections import OrderedDict
from subprocess import CalledProcessError

from pex.atomic_directory import atomic_directory
from pex.common import chmod_plus_x, is_exe, pluralize, safe_mkdtemp, safe_open
from pex.compatibility import shlex_quote
from pex.dist_metadata import NamedEntryPoint, parse_entry_point
from pex.exceptions import production_assert
from pex.fetcher import URLFetcher
from pex.hashing import Sha256
from pex.layout import Layout
from pex.pep_440 import Version
from pex.pex import PEX
from pex.result import Error, try_
from pex.scie.model import ScieConfiguration, ScieInfo, SciePlatform, ScieStyle, ScieTarget
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.packaging.version import InvalidVersion
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper
from pex.variables import ENV, Variables, unzip_dir_relpath

if TYPE_CHECKING:
    from typing import Any, Dict, Iterator, List, Optional, Union, cast

    import attr  # vendor:skip
    import toml  # vendor:skip
else:
    from pex.third_party import attr, toml


@attr.s(frozen=True)
class Manifest(object):
    target = attr.ib()  # type: ScieTarget
    path = attr.ib()  # type: str

    def binary_name(self, binary_name):
        # type: (str) -> str
        return self.target.platform.binary_name(binary_name)

    def qualified_binary_name(self, binary_name):
        # type: (str) -> str
        return self.target.platform.qualified_binary_name(binary_name)


SCIENCE_RELEASES_URL = "https://github.com/a-scie/lift/releases"
MIN_SCIENCE_VERSION = Version("0.3.0")
SCIENCE_REQUIREMENT = SpecifierSet("~={min_version}".format(min_version=MIN_SCIENCE_VERSION))


def _science_binary_url(suffix=""):
    # type: (str) -> str
    return "{science_releases_url}/download/v{version}/{binary}{suffix}".format(
        science_releases_url=SCIENCE_RELEASES_URL,
        version=MIN_SCIENCE_VERSION.raw,
        binary=SciePlatform.CURRENT.qualified_binary_name("science-fat"),
        suffix=suffix,
    )


PTEX_VERSION = "1.1.1"
SCIE_JUMP_VERSION = "1.1.1"


def create_manifests(
    configuration,  # type: ScieConfiguration
    name,  # type: str
    pex,  # type: PEX
):
    # type: (...) -> Iterator[Manifest]

    pex_info = pex.pex_info(include_env_overrides=False)
    pex_root = "{scie.bindings}/pex_root"

    configure_binding_args = ["{pex}", "{configure-binding.py}"]
    # N.B.: For the venv case, we let the configure-binding calculate the installed PEX dir
    # (venv dir) at runtime since it depends on the interpreter executing the venv PEX.
    if not pex_info.venv:
        configure_binding_args.append("--installed-pex-dir")
        if pex.layout is Layout.LOOSE:
            configure_binding_args.append("{pex}")
        else:
            production_assert(pex_info.pex_hash is not None)
            pex_hash = cast(str, pex_info.pex_hash)
            configure_binding_args.append(os.path.join(pex_root, unzip_dir_relpath(pex_hash)))

    env_default = {
        "PEX_ROOT": pex_root,
    }

    commands = []  # type: List[Dict[str, Any]]
    entrypoints = configuration.options.busybox_entrypoints
    if entrypoints:
        pex_entry_point = parse_entry_point(pex_info.entry_point)

        def replace_env(
            named_entry_point,  # type: NamedEntryPoint
            **env  # type: str
        ):
            # type: (...) -> Dict[str, str]
            return dict(
                pex_info.inject_env if named_entry_point.entry_point == pex_entry_point else {},
                **env
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
            return {
                "name": named_entry_point.name,
                "env": {
                    "default": env_default,
                    "replace": replace_env(
                        named_entry_point, PEX_MODULE=str(named_entry_point.entry_point)
                    ),
                    "remove_exact": ["PEX_INTERPRETER", "PEX_SCRIPT", "PEX_VENV"],
                },
                "exe": "{scie.bindings.configure:PYTHON}",
                "args": args(named_entry_point, "{scie.bindings.configure:PEX}"),
            }

        if pex_info.venv:
            # N.B.: Executing the console script directly instead of bouncing through the PEX
            # __main__.py using PEX_SCRIPT saves ~10ms of re-exec overhead in informal testing; so
            # it's worth specializing here.
            commands.extend(
                {
                    "name": named_entry_point.name,
                    "env": {
                        "default": env_default,
                        "replace": replace_env(named_entry_point),
                        "remove_exact": ["PEX_INTERPRETER", "PEX_MODULE", "PEX_SCRIPT", "PEX_VENV"],
                    },
                    "exe": "{scie.bindings.configure:PYTHON}",
                    "args": args(
                        named_entry_point,
                        "{scie.bindings.configure:VENV_BIN_DIR_PLUS_SEP}" + named_entry_point.name,
                    ),
                }
                for named_entry_point in entrypoints.console_scripts_manifest.collect(pex)
            )
        else:
            commands.extend(map(create_cmd, entrypoints.console_scripts_manifest.collect(pex)))
        commands.extend(map(create_cmd, entrypoints.ad_hoc_entry_points))
    else:
        commands.append(
            {
                "env": {
                    "default": env_default,
                    "remove_exact": ["PEX_VENV"],
                },
                "exe": "{scie.bindings.configure:PYTHON}",
                "args": ["{scie.bindings.configure:PEX}"],
            }
        )

    lift = {
        "name": name,
        "ptex": {
            "id": "ptex",
            "version": PTEX_VERSION,
            "argv1": "{scie.env.PEX_BOOTSTRAP_URLS={scie.lift}}",
        },
        "scie_jump": {"version": SCIE_JUMP_VERSION},
        "files": [{"name": "configure-binding.py"}, {"name": "pex"}],
        "commands": commands,
        "bindings": [
            {
                "env": {
                    "default": env_default,
                    "remove_exact": ["PATH"],
                    "remove_re": ["PEX_.*"],
                    "replace": {
                        "PEX_INTERPRETER": "1",
                        # We can get a warning about too-long script shebangs, but this is not
                        # relevant since we above run the PEX via python and not via shebang.
                        "PEX_EMIT_WARNINGS": "0",
                    },
                },
                "name": "configure",
                "exe": "#{cpython:python}",
                "args": configure_binding_args,
            }
        ],
    }  # type: Dict[str, Any]

    for target in configuration.targets:
        manifest_path = os.path.join(
            safe_mkdtemp(),
            target.platform.qualified_file_name("{name}-lift.toml".format(name=name)),
        )
        with safe_open(manifest_path, "w") as fp:
            toml.dump(
                {
                    "lift": dict(
                        lift,
                        platforms=[target.platform.value],
                        interpreters=[
                            {
                                "id": "cpython",
                                "provider": "PythonBuildStandalone",
                                "release": target.pbs_release,
                                "version": target.version_str,
                                "lazy": configuration.options.style is ScieStyle.LAZY,
                            }
                        ],
                    )
                },
                fp,
            )
        yield Manifest(target=target, path=manifest_path)


def _science_dir(
    env,  # type: Variables
    *components  # type: str
):
    # type: (...) -> str
    return os.path.join(env.PEX_ROOT, "scies", "science", MIN_SCIENCE_VERSION.raw, *components)


def _science_binary_names():
    # type: () -> Iterator[str]
    yield SciePlatform.CURRENT.binary_name("science-fat")
    yield SciePlatform.CURRENT.qualified_binary_name("science-fat")
    yield SciePlatform.CURRENT.binary_name("science")
    yield SciePlatform.CURRENT.qualified_binary_name("science")


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


def _ensure_science(
    url_fetcher=None,  # type: Optional[URLFetcher]
    science_binary_url=None,  # type: Optional[str]
    env=ENV,  # type: Variables
):
    # type: (...) -> str

    target_dir = _science_dir(env, "bin")
    with atomic_directory(target_dir=target_dir) as atomic_dir:
        if not atomic_dir.is_finalized():
            target_science = os.path.join(atomic_dir.work_dir, "science")
            path_science = _path_science()
            if path_science:
                shutil.copy(path_science, target_science)
            else:
                fetcher = url_fetcher or URLFetcher()
                with open(target_science, "wb") as write_fp, fetcher.get_body_stream(
                    science_binary_url or _science_binary_url()
                ) as read_fp:
                    shutil.copyfileobj(read_fp, write_fp)
                chmod_plus_x(target_science)

                if science_binary_url:
                    custom_science_binary_version = try_(
                        _is_compatible_science_binary(target_science, source=science_binary_url)
                    )
                    TRACER.log(
                        "Using custom science binary from {source} with version {version}.".format(
                            source=science_binary_url, version=custom_science_binary_version.raw
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
                                science_binary_url=science_binary_url,
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

    science = _ensure_science(
        url_fetcher=url_fetcher,
        science_binary_url=configuration.options.science_binary_url,
        env=env,
    )
    name = re.sub(r"\.pex$", "", os.path.basename(pex_file), flags=re.IGNORECASE)
    pex = PEX(pex_file)
    use_platform_suffix = len(configuration.targets) > 1

    errors = OrderedDict()  # type: OrderedDict[Manifest, str]
    for manifest in create_manifests(configuration, name, pex):
        args = [science, "--cache-dir", _science_dir(env, "cache")]
        if env.PEX_VERBOSE:
            args.append("-{verbosity}".format(verbosity="v" * env.PEX_VERBOSE))
        dest_dir = os.path.dirname(os.path.abspath(pex_file))
        args.extend(
            [
                "lift",
                "--file",
                "pex={pex_file}".format(pex_file=pex_file),
                "--file",
                "configure-binding.py={configure_binding}".format(
                    configure_binding=os.path.join(
                        os.path.dirname(__file__), "configure-binding.py"
                    )
                ),
                "build",
                "--dest-dir",
                dest_dir,
            ]
        )
        if use_platform_suffix:
            args.append("--use-platform-suffix")
        args.append(manifest.path)
        with open(os.devnull, "wb") as devnull:
            process = subprocess.Popen(args=args, stdout=devnull, stderr=subprocess.PIPE)
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
                    target=manifest.target,
                    file=os.path.join(
                        dest_dir,
                        manifest.qualified_binary_name(name)
                        if use_platform_suffix
                        else manifest.binary_name(name),
                    ),
                )

    if errors:
        raise ScienceError(
            "Failed to build {count} {scies}:\n\n{errors}".format(
                count=len(errors),
                scies=pluralize(errors, "scie"),
                errors="\n\n".join(
                    "{index}. For CPython {version} on {platform}: {err}".format(
                        index=index,
                        platform=manifest.target.platform,
                        version=manifest.target.version_str,
                        err=err,
                    )
                    for index, (manifest, err) in enumerate(errors.items(), start=1)
                ),
            )
        )
