# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pkgutil
from dataclasses import dataclass

import toml


@dataclass(frozen=True)
class ScieConfig:
    @classmethod
    def load(
        cls, *, pbs_release: str | None = None, python_version: str | None = None
    ) -> ScieConfig:
        data = pkgutil.get_data(__name__, "package.toml")
        assert data is not None, f"Expected to find a sibling package.toml file to {__file__}."
        scie_config = toml.loads(data.decode())["scie"]
        return cls(
            pbs_release=pbs_release or scie_config["pbs-release"],
            python_version=python_version or scie_config["python-version"],
            pex_extras=tuple(scie_config["pex-extras"]),
            platforms=tuple(scie_config["platforms"]),
        )

    pbs_release: str
    python_version: str
    pex_extras: tuple[str, ...]
    platforms: tuple[str, ...]
