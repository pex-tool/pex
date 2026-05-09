# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import shutil
import subprocess
from subprocess import CalledProcessError

from pex.atomic_directory import atomic_directory
from pex.cache.dirs import CacheDir
from pex.common import safe_rmtree
from pex.executables import chmod_plus_x
from pex.fetcher import URLFetcher
from pex.fs import safe_rename
from pex.hashing import Sha256
from pex.os import is_exe
from pex.pep_440 import Version
from pex.rc.model import File, NativeRuntimeConfiguration, Url
from pex.result import Error, try_
from pex.sysconfig import LibC, SysPlatform
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.packaging.version import InvalidVersion
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper
from pex.variables import ENV, Variables

if TYPE_CHECKING:
    from typing import Iterator, Optional, Union


PEXRC_RELEASES_URL = "https://github.com/pex-tool/pex.rc/releases"
MIN_PEXRC_VERSION = Version("0.12.3")
PEXRC_REQUIREMENT = SpecifierSet("~={min_version}".format(min_version=MIN_PEXRC_VERSION))


def _pexrc_platform_suffix():
    # type: () -> str
    if SysPlatform.CURRENT == SysPlatform.LINUX_AARCH64:
        if SysPlatform.CURRENT.libc == LibC.MUSL:
            return "aarch64-linux-musl"
        return "aarch64-linux-gnu"
    elif SysPlatform.CURRENT == SysPlatform.LINUX_ARMV7L:
        return "armv7-linux-gnueabihf"
    elif SysPlatform.CURRENT == SysPlatform.LINUX_PPC64LE:
        return "powerpc64le-linux-gnu"
    elif SysPlatform.CURRENT == SysPlatform.LINUX_RISCV64:
        return "riscv64gc-linux-gnu"
    elif SysPlatform.CURRENT == SysPlatform.LINUX_S390X:
        return "s390x-linux-gnu"
    elif SysPlatform.CURRENT == SysPlatform.LINUX_X86_64:
        if SysPlatform.CURRENT.libc == LibC.MUSL:
            return "x86_64-linux-musl"
        return "x86_64-linux-gnu"
    elif SysPlatform.CURRENT == SysPlatform.MACOS_AARCH64:
        return "aarch64-macos"
    elif SysPlatform.CURRENT == SysPlatform.MACOS_X86_64:
        return "x86_64-macos"
    elif SysPlatform.CURRENT == SysPlatform.WINDOWS_AARCH64:
        return "aarch64-windows.exe"
    elif SysPlatform.CURRENT == SysPlatform.WINDOWS_X86_64:
        return "x86_64-windows.exe"
    raise ValueError("There is no `pexrc` support for the current platform.")


def _pexrc_binary_names():
    # type: () -> Iterator[str]
    yield SysPlatform.CURRENT.binary_name("pexrc")
    yield "pexrc-{suffix}".format(suffix=_pexrc_platform_suffix())


def _pexrc_binary_url(suffix=""):
    # type: (str) -> str
    return "{pexrc_releases_url}/download/v{version}/pexrc-{platform_suffix}{suffix}".format(
        pexrc_releases_url=PEXRC_RELEASES_URL,
        version=MIN_PEXRC_VERSION.raw,
        platform_suffix=_pexrc_platform_suffix(),
        suffix=suffix,
    )


def _is_compatible_pexrc_binary(
    binary,  # type: str
    source=None,  # type: Optional[str]
):
    # type: (...) -> Union[Version, Error]
    try:
        # N.B.: The versions look like `pexrc X.Y.Z`.
        output = subprocess.check_output(args=[binary, "--version"]).decode("utf-8").strip()
        components = output.rsplit(" ", 1)
        if len(components) != 2 or components[0] != "pexrc":
            return Error(
                "Failed to determine --version of pexrc binary at {source}; "
                "invalid --version output: {output}".format(source=source or binary, output=output)
            )
        version = Version(components[1])
    except (CalledProcessError, InvalidVersion) as e:
        return Error(
            "Failed to determine --version of pexrc binary at {source}: {err}".format(
                source=source or binary, err=e
            )
        )
    else:
        if version.raw in PEXRC_REQUIREMENT:
            return version
        return Error(
            "The pexrc binary at {source} is version {version} which does not match Pex's "
            "pexrc requirement of {pexrc_requirement}.".format(
                source=source or binary,
                version=version.raw,
                pexrc_requirement=PEXRC_REQUIREMENT,
            )
        )


def _path_pexrc():
    # type: () -> Optional[str]
    for path_element in os.environ.get("PATH", os.defpath).split(os.pathsep):
        for binary in (
            os.path.join(path_element, binary_name) for binary_name in _pexrc_binary_names()
        ):
            if not is_exe(binary):
                continue
            if isinstance(_is_compatible_pexrc_binary(binary), Error):
                continue
            return binary
    return None


def ensure_pexrc(
    url_fetcher=None,  # type: Optional[URLFetcher]
    pexrc_binary=None,  # type: Optional[Union[File, Url]]
    env=ENV,  # type: Variables
):
    # type: (...) -> str

    if isinstance(pexrc_binary, File):
        if not is_exe(pexrc_binary):
            raise ValueError(
                "The --pexrc-binary at {source} is not an executable.".format(source=pexrc_binary)
            )
        custom_pexrc_binary_version = try_(_is_compatible_pexrc_binary(pexrc_binary))
        TRACER.log(
            "Using custom pexrc binary from {source} with version "
            "{version}.".format(source=pexrc_binary, version=custom_pexrc_binary_version.raw)
        )
        return pexrc_binary

    target_dir = CacheDir.RC.path("bin", MIN_PEXRC_VERSION.raw, pex_root=env)
    with atomic_directory(target_dir=target_dir) as atomic_dir:
        if not atomic_dir.is_finalized():
            target_pexrc = os.path.join(atomic_dir.work_dir, "pexrc")
            if not pexrc_binary:
                path_pexrc = _path_pexrc()
                if path_pexrc:
                    shutil.copy(path_pexrc, target_pexrc)
            if not os.path.exists(target_pexrc):
                fetcher = url_fetcher or URLFetcher()
                url = pexrc_binary or _pexrc_binary_url()
                TRACER.log("Fetching pexrc binary from {url}...".format(url=url))
                with open(target_pexrc, "wb") as write_fp, fetcher.get_body_stream(url) as read_fp:
                    shutil.copyfileobj(read_fp, write_fp)
                chmod_plus_x(target_pexrc)

                if pexrc_binary:
                    custom_pexrc_binary_version = try_(
                        _is_compatible_pexrc_binary(target_pexrc, source=pexrc_binary)
                    )
                    TRACER.log(
                        "Using custom pexrc binary from {source} with version "
                        "{version}.".format(
                            source=pexrc_binary, version=custom_pexrc_binary_version.raw
                        )
                    )
                else:
                    # Since we used the canonical GitHub Releases URL, we know a checksum file is
                    # available we can use to verify.
                    pexrc_sha256_url = _pexrc_binary_url(".sha256")
                    with fetcher.get_body_stream(pexrc_sha256_url) as fp:
                        expected_sha256, _, _ = fp.read().decode("utf-8").partition(" ")
                    actual_sha256 = CacheHelper.hash(target_pexrc, hasher=Sha256)
                    if expected_sha256 != actual_sha256:
                        raise ValueError(
                            "The pexrc binary downloaded from {pexrc_binary_url} does not "
                            "match the expected SHA-256 fingerprint recorded in "
                            "{pexrc_sha256_url}.\n"
                            "Expected {expected_sha256} but found {actual_sha256}.".format(
                                pexrc_binary_url=url,
                                pexrc_sha256_url=pexrc_sha256_url,
                                expected_sha256=expected_sha256,
                                actual_sha256=actual_sha256,
                            )
                        )
    return os.path.join(target_dir, "pexrc")


class PexrcError(Exception):
    """Indicates an error executing pexrc."""


def inject(
    configuration,  # type: NativeRuntimeConfiguration
    pex_file,  # type: str
    url_fetcher=None,  # type: Optional[URLFetcher]
    env=ENV,  # type: Variables
):
    # type: (...) -> None
    pexrc = ensure_pexrc(
        url_fetcher=url_fetcher,
        pexrc_binary=configuration.pexrc_binary,
        env=env,
    )

    args = [pexrc, "inject"]
    if configuration.max_jobs:
        args.append("--jobs")
        args.append(str(configuration.max_jobs))
    if configuration.compression_method:
        args.append("--compression-method")
        args.append(configuration.compression_method.value)
    if configuration.compression_level:
        args.append("--compression-level")
        args.append(str(configuration.compression_level))
    args.append(pex_file)

    with open(os.devnull, "wb") as devnull:
        process = subprocess.Popen(args=args, stdout=devnull, stderr=subprocess.PIPE)
        _, stderr = process.communicate()
        if process.returncode != 0:
            raise PexrcError(
                "Failed to inject native PEX runtime using pexrc.\n"
                "Command {command} exited {returncode} with STDERR:\n"
                "{stderr}".format(
                    command=args, returncode=process.returncode, stderr=stderr.decode("utf-8")
                )
            )
    stem, _ = os.path.splitext(pex_file)
    expected_pexrc = "{stem}.pexrc".format(stem=stem)
    if not os.path.exists(expected_pexrc):
        raise PexrcError(
            "Failed to inject native PEX runtime using pexrc.\n"
            "Expected native PEX {expected_pexrc} to be created but it was not found.".format(
                expected_pexrc=expected_pexrc
            )
        )

    if os.path.isfile(pex_file):
        safe_rename(expected_pexrc, pex_file)
    else:
        safe_rmtree(pex_file)
        safe_rename(expected_pexrc, pex_file)
