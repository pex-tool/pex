# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import base64
import json
import pkgutil
import platform
from collections import Counter
from dataclasses import dataclass
from typing import Any

import toml


@dataclass(frozen=True)
class PlatformConfig:
    @classmethod
    def load(
        cls,
        *,
        name: str,
        platform_data: dict[str, Any],
        default_pbs_release: str,
        default_python_version: str
    ) -> PlatformConfig:
        return cls(
            name=name,
            pbs_release=platform_data.get("pbs-release", default_pbs_release),
            python_version=platform_data.get("python-version", default_python_version),
            required=platform_data.get("required", True),
        )

    name: str
    pbs_release: str
    python_version: str
    required: bool = True


@dataclass(frozen=True)
class ScieConfig:
    @classmethod
    def load(
        cls,
        *,
        pbs_release: str | None = None,
        python_version: str | None = None,
        encoded_config: str | None = None
    ) -> ScieConfig:
        if encoded_config:
            scie_config = json.loads(base64.urlsafe_b64decode(encoded_config))
        else:
            data = pkgutil.get_data(__name__, "package.toml")
            assert data is not None, f"Expected to find a sibling package.toml file to {__file__}."
            scie_config = toml.loads(data.decode())["scie"]
        default_pbs_release = pbs_release or scie_config["pbs-release"]
        default_python_version = python_version or scie_config["python-version"]
        return cls(
            platforms=tuple(
                PlatformConfig.load(
                    name=platform_name,
                    platform_data=platform_data,
                    default_pbs_release=default_pbs_release,
                    default_python_version=default_python_version,
                )
                for platform_name, platform_data in scie_config["platforms"].items()
            ),
            pex_extras=tuple(scie_config.get("pex-extras", ())),
            extra_lock_args=tuple(scie_config.get("extra-lock-args", ())),
        )

    platforms: tuple[PlatformConfig, ...]
    pex_extras: tuple[str, ...] = ()
    extra_lock_args: tuple[str, ...] = ()

    def current_platform(self) -> PlatformConfig:
        system = platform.system().lower()
        if system == "darwin":
            system = "macos"
        machine = platform.machine().lower()
        if machine in ("aarch64", "arm64"):
            plat = f"{system}-aarch64"
        elif machine in ("armv7l", "armv8l"):
            plat = f"{system}-armv7l"
        elif machine in ("amd64", "x86_64"):
            plat = f"{system}-x86_64"
        else:
            raise ValueError(f"Unexpected platform.machine(): {platform.machine()}")

        for platform_config in self.platforms:
            if platform_config.name == plat:
                return platform_config
        raise KeyError(
            f"This scie configuration does not contain an entry for platform {plat!r}, only the "
            f"following platforms are defined: "
            f"{', '.join(platform_config.name for platform_config in self.platforms)}"
        )

    def encode(self) -> str:
        pbs_releases: Counter[str] = Counter()
        python_versions: Counter[str] = Counter()
        for platform_config in self.platforms:
            pbs_releases[platform_config.pbs_release] += 1
            python_versions[platform_config.python_version] += 1
        default_pbs_release, _count = pbs_releases.most_common(n=1)[0]
        default_python_version, _count = python_versions.most_common(n=1)[0]

        platforms = {}
        for platform_config in self.platforms:
            data: dict[str, Any] = {}
            if platform_config.pbs_release != default_pbs_release:
                data["pbs-release"] = platform_config.pbs_release
            if platform_config.python_version != default_python_version:
                data["python-version"] = platform_config.python_version
            if not platform_config.required:
                data["required"] = False
            platforms[platform_config.name] = data

        return base64.urlsafe_b64encode(
            json.dumps(
                {
                    "pbs-release": default_pbs_release,
                    "python-version": default_python_version,
                    "pex-extras": self.pex_extras,
                    "extra-lock-args": self.extra_lock_args,
                    "platforms": platforms,
                }
            ).encode()
        ).decode("ascii")
