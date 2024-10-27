# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

from pex.enum import Enum
from pex.typing import TYPE_CHECKING
from pex.variables import ENV, Variables

if TYPE_CHECKING:
    from typing import Iterable, Iterator, Union


class CacheDir(Enum["CacheDir.Value"]):
    class Value(Enum.Value):
        def __init__(
            self,
            value,  # type: str
            name,  # type: str
            version,  # type: int
            description,  # type: str
            dependencies=(),  # type: Iterable[CacheDir.Value]
            can_purge=True,  # type: bool
        ):
            Enum.Value.__init__(self, value)
            self.name = name
            self.version = version
            self.description = description
            self.dependencies = tuple(dependencies)
            self.can_purge = can_purge

        @property
        def rel_path(self):
            # type: () -> str
            return os.path.join(self.value, str(self.version))

        def path(
            self,
            *subdirs,  # type: str
            **kwargs  # type: Union[str, Variables]
        ):
            # type: (...) -> str
            pex_root = kwargs.get("pex_root", ENV)
            return os.path.join(
                pex_root.PEX_ROOT if isinstance(pex_root, Variables) else pex_root,
                self.rel_path,
                *subdirs
            )

        def iter_transitive_dependents(self):
            # type: () -> Iterator[CacheDir.Value]
            for cache_dir in CacheDir.values():
                if self in cache_dir.dependencies:
                    yield cache_dir
                    for dependent in cache_dir.iter_transitive_dependents():
                        yield dependent

    BOOTSTRAP_ZIPS = Value(
        "bootstrap_zips",
        version=0,
        name="Packed Bootstraps",
        description="PEX runtime bootstrap code, zipped up for `--layout packed` PEXes.",
    )

    BOOTSTRAPS = Value(
        "bootstraps",
        version=0,
        name="Bootstraps",
        description="PEX runtime bootstrap code.",
    )

    BUILT_WHEELS = Value(
        "built_wheels",
        version=0,
        name="Built Wheels",
        description="Wheels built by Pex from resolved sdists when creating PEX files.",
    )

    DBS = Value(
        "dbs",
        version=0,
        name="Pex Internal Databases",
        description="Databases Pex uses for caches and to track cache structure.",
        can_purge=False,
    )

    DOCS = Value(
        "docs",
        version=0,
        name="Pex Docs",
        description="Artifacts used in serving Pex docs via `pex --docs` and `pex3 docs`.",
    )

    DOWNLOADS = Value(
        "downloads",
        version=0,
        name="Lock Artifact Downloads",
        description="Distributions downloaded when resolving from a Pex lock file.",
    )

    INSTALLED_WHEELS = Value(
        "installed_wheels",
        version=0,
        name="Pre-installed Wheels",
        description=(
            "Pre-installed wheel chroots used to both build PEXes and serve as runtime `sys.path` "
            "entries."
        ),
    )

    INTERPRETERS = Value(
        "interpreters",
        version=1,
        name="Interpreters",
        description="Information about interpreters found on the system.",
    )

    ISOLATED = Value(
        "isolated",
        version=0,
        name="Isolated Pex Code",
        description="The Pex codebase isolated for internal use in subprocesses.",
    )

    PACKED_WHEELS = Value(
        "packed_wheels",
        version=0,
        name="Packed Wheels",
        description=(
            "The same content as {installed_wheels!r}, but zipped up for `--layout packed` "
            "PEXes.".format(installed_wheels=INSTALLED_WHEELS.rel_path)
        ),
    )

    PIP = Value(
        "pip",
        version=1,
        name="Pip Versions",
        description="Isolated Pip caches and Pip PEXes Pex uses to resolve distributions.",
    )

    PLATFORMS = Value(
        "platforms",
        version=0,
        name="Abbreviated Platforms",
        description=(
            "Information calculated about abbreviated platforms specified via `--platform`."
        ),
    )

    SCIES = Value(
        "scies",
        version=0,
        name="Scie Tools",
        description="Tools and caches used when building PEX scies via `--scie {eager,lazy}`.",
    )

    TOOLS = Value(
        "tools",
        version=0,
        name="Pex Tools",
        description="Caches for the various `PEX_TOOLS=1` / `pex-tools` subcommands.",
    )

    USER_CODE = Value(
        "user_code",
        version=0,
        name="User Code",
        description=(
            "User code added to PEX files using `-D` / `--sources-directory`, `-P` / `--package` "
            "and `-M` / `--module`."
        ),
    )

    UNZIPPED_PEXES = Value(
        "unzipped_pexes",
        version=0,
        name="Unzipped PEXes",
        description="The unzipped PEX files executed on this machine.",
        dependencies=[BOOTSTRAPS, USER_CODE, INSTALLED_WHEELS],
    )

    VENVS = Value(
        "venvs",
        version=0,
        name="Virtual Environments",
        description="Virtual environments generated at runtime for `--venv` mode PEXes.",
        dependencies=[INSTALLED_WHEELS],
    )
