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
from pex.common import is_exe, pluralize, safe_mkdtemp, safe_open
from pex.compatibility import shlex_quote
from pex.exceptions import production_assert
from pex.fetcher import URLFetcher
from pex.hashing import Sha256
from pex.pep_440 import Version
from pex.pex_info import PexInfo
from pex.scie.model import ScieConfiguration, ScieInfo, SciePlatform, ScieStyle, ScieTarget
from pex.third_party.packaging.version import InvalidVersion
from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper
from pex.variables import ENV, Variables, unzip_dir_relpath

if TYPE_CHECKING:
    from typing import Any, Dict, Iterator, Optional, cast

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


MIN_SCIENCE_VERSION = Version("0.3.0")
PTEX_VERSION = "1.1.1"
SCIE_JUMP_VERSION = "1.1.1"


def create_manifests(
    configuration,  # type: ScieConfiguration
    name,  # type: str
    pex_info,  # type: PexInfo
):
    # type: (...) -> Iterator[Manifest]

    pex_root = "{scie.bindings}/pex_root"
    if pex_info.venv:
        # We let the configure-binding calculate the venv dir at runtime since it depends on the
        # interpreter executing the venv PEX.
        installed_pex_dir = ""
    else:
        production_assert(pex_info.pex_hash is not None)
        pex_hash = cast(str, pex_info.pex_hash)
        installed_pex_dir = os.path.join(pex_root, unzip_dir_relpath(pex_hash))

    env_replace = {
        "PEX_ROOT": pex_root,
    }
    env = {
        "remove_re": {"PEX_.*"},
        "replace": env_replace,
    }

    lift = {
        "name": name,
        "ptex": {
            "id": "ptex",
            "version": PTEX_VERSION,
            "argv1": "{scie.env.PEX_BOOTSTRAP_URLS={scie.lift}}",
        },
        "scie_jump": {"version": SCIE_JUMP_VERSION},
        "files": [{"name": "configure-binding.py"}, {"name": "pex"}],
        "commands": [
            {
                "env": env,
                "exe": "{scie.bindings.configure:PYTHON}",
                "args": ["{scie.bindings.configure:PEX}"],
            }
        ],
        "bindings": [
            {
                "env": dict(
                    env,
                    replace=dict(
                        env_replace,
                        PEX_INTERPRETER="1",
                        _PEX_SCIE_INSTALLED_PEX_DIR=installed_pex_dir,
                        # We can get a warning about too-long script shebangs, but this is not
                        # relevant since we above run the PEX via python and not via shebang.
                        PEX_EMIT_WARNINGS="0",
                    ),
                ),
                "name": "configure",
                "exe": "#{cpython:python}",
                "args": ["{pex}", "{configure-binding.py}"],
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
    return os.path.join(env.PEX_ROOT, "scies", "science", str(MIN_SCIENCE_VERSION), *components)


def _qualified_science_binary_name():
    # type: () -> str
    return SciePlatform.current().qualified_binary_name("science")


def _science_binary_names():
    # type: () -> Iterator[str]
    yield "science"
    yield _qualified_science_binary_name()


def _path_science():
    # type: () -> Optional[str]
    for path_element in os.environ.get("PATH", os.defpath).split(os.pathsep):
        for binary in (
            os.path.join(path_element, binary_name) for binary_name in _science_binary_names()
        ):
            if not is_exe(binary):
                continue
            try:
                if (
                    Version(subprocess.check_output(args=[binary, "--version"]).decode("utf-8"))
                    < MIN_SCIENCE_VERSION
                ):
                    continue
            except (CalledProcessError, InvalidVersion):
                continue
            return binary
    return None


def _science_binary_url(suffix=""):
    # type: (str) -> str
    return "https://github.com/a-scie/science/releases/download/v{version}/{binary}{suffix}".format(
        version=MIN_SCIENCE_VERSION,
        binary=_qualified_science_binary_name(),
        suffix=suffix,
    )


def _ensure_science(
    url_fetcher=None,  # type: Optional[URLFetcher]
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
                science_binary_url = _science_binary_url()
                with open(target_science, "wb") as write_fp, fetcher.get_body_stream(
                    science_binary_url
                ) as read_fp:
                    shutil.copyfileobj(read_fp, write_fp)

                science_sha256_url = _science_binary_url(".sha256")
                with fetcher.get_body_stream(science_sha256_url) as fp:
                    expected_sha256, _, _ = fp.read().decode("utf-8").partition(" ")
                actual_sha256 = CacheHelper.hash(target_science, hasher=Sha256)
                if expected_sha256 != actual_sha256:
                    raise ValueError(
                        "The science binary downloaded from {science_binary_url} does not match "
                        "the expected SHA-256 fingerprint recorded in {science_sha256_url}.\n"
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

    science = _ensure_science(url_fetcher=url_fetcher, env=env)
    name = re.sub(r"\.pex$", "", os.path.basename(pex_file), flags=re.IGNORECASE)
    pex_info = PexInfo.from_pex(pex_file)
    use_platform_suffix = len(configuration.targets) > 1
    errors = OrderedDict()  # type: OrderedDict[Manifest, str]
    for manifest in create_manifests(configuration, name, pex_info):
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
