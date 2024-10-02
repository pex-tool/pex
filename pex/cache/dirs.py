# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import os

from pex.enum import Enum
from pex.typing import TYPE_CHECKING, cast
from pex.variables import ENV, Variables

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, Optional, Type, TypeVar, Union


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


if TYPE_CHECKING:
    _AtomicCacheDir = TypeVar("_AtomicCacheDir", bound="AtomicCacheDir")


class AtomicCacheDir(str):
    @staticmethod
    def __new__(
        cls,  # type: Type[_AtomicCacheDir]
        path,  # type: str
        *args,  # type: Any
        **kwargs  # type: Any
    ):
        # type: (...) -> _AtomicCacheDir
        # MyPy incorrectly flags the call to str.__new__(cls, path) for Python 2.7.
        return cast("_AtomicCacheDir", str.__new__(cls, path))  # type: ignore[call-arg]

    def __init__(
        self,
        path,  # type: str
        *args,  # type: Any
        **kwargs  # type: Any
    ):
        # type: (...) -> None
        self.path = path

    def __repr__(self):
        # type: () -> str
        return "{clazz}(path={path})".format(clazz=self.__class__.__name__, path=self.path)


class UnzipDir(AtomicCacheDir):
    @classmethod
    def create(
        cls,
        pex_hash,  # type: str
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        # type: (...) -> UnzipDir
        unzip_dir = CacheDir.UNZIPPED_PEXES.path(pex_hash, pex_root=pex_root)
        return cls(path=unzip_dir, pex_hash=pex_hash)

    @classmethod
    def iter_all(cls, pex_root=ENV):
        # type: (Union[str, Variables]) -> Iterator[UnzipDir]
        for unzip_dir in glob.glob(CacheDir.UNZIPPED_PEXES.path("*", pex_root=pex_root)):
            if os.path.isdir(unzip_dir):
                pex_hash = os.path.basename(unzip_dir)
                yield UnzipDir(path=unzip_dir, pex_hash=pex_hash)

    def __init__(
        self,
        path,  # type: str
        pex_hash,  # type: str
    ):
        # type: (...) -> None
        super(UnzipDir, self).__init__(path)
        self.pex_hash = pex_hash


class VenvDir(AtomicCacheDir):
    @classmethod
    def create(
        cls,
        pex_hash,  # type: str
        contents_hash,  # type: str
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        # type: (...) -> VenvDir
        venv_dir = CacheDir.VENVS.path(pex_hash, contents_hash, pex_root=pex_root)
        return cls(path=venv_dir, pex_hash=pex_hash, contents_hash=contents_hash, pex_root=pex_root)

    def __init__(
        self,
        path,  # type: str
        pex_hash,  # type: str
        contents_hash,  # type: str
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        # type: (...) -> None
        super(VenvDir, self).__init__(path)
        self.pex_hash = pex_hash
        self.contents_hash = contents_hash
        self.pex_root = pex_root


class VenvDirs(AtomicCacheDir):
    SHORT_SYMLINK_NAME = "venv"

    @classmethod
    def create(
        cls,
        short_hash,  # type: str
        pex_hash,  # type: str
        contents_hash,  # type: str
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        # type: (...) -> VenvDirs
        venv_dir = VenvDir.create(pex_hash, contents_hash, pex_root=pex_root)
        return cls(venv_dir=venv_dir, short_hash=short_hash)

    @classmethod
    def iter_all(cls, pex_root=ENV):
        # type: (Union[str, Variables]) -> Iterator[VenvDirs]
        for venv_short_dir_symlink in glob.glob(
            CacheDir.VENVS.path("s", "*", cls.SHORT_SYMLINK_NAME, pex_root=pex_root)
        ):
            if not os.path.isdir(venv_short_dir_symlink):
                continue

            head, _venv = os.path.split(venv_short_dir_symlink)
            short_hash = os.path.basename(head)

            venv_dir_path = os.path.realpath(venv_short_dir_symlink)
            head, contents_hash = os.path.split(venv_dir_path)
            pex_hash = os.path.basename(head)
            venv_dir = VenvDir(path=venv_dir_path, pex_hash=pex_hash, contents_hash=contents_hash)

            yield VenvDirs(venv_dir=venv_dir, short_hash=short_hash)

    @staticmethod
    def __new__(
        cls,
        venv_dir,  # type: VenvDir
        short_hash,  # type: str
    ):
        # type: (...) -> VenvDirs
        return cast(VenvDirs, super(VenvDirs, cls).__new__(cls, venv_dir.path))

    def __getnewargs__(self):
        return VenvDir.create(self.pex_hash, self.contents_hash, self._pex_root), self.short_hash

    def __init__(
        self,
        venv_dir,  # type: VenvDir
        short_hash,  # type: str
    ):
        # type: (...) -> None
        super(VenvDirs, self).__init__(venv_dir.path)
        self.short_hash = short_hash
        self.pex_hash = venv_dir.pex_hash
        self.contents_hash = venv_dir.contents_hash
        self._pex_root = venv_dir.pex_root

    @property
    def short_dir(self):
        # type: () -> str
        return CacheDir.VENVS.path("s", self.short_hash, pex_root=self._pex_root)


class InstalledWheelDir(AtomicCacheDir):
    @classmethod
    def create(
        cls,
        wheel_name,  # type: str
        install_hash,  # type: str
        wheel_hash=None,  # type: Optional[str]
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        # type: (...) -> InstalledWheelDir

        wheel_dir = CacheDir.INSTALLED_WHEELS.path(install_hash, wheel_name, pex_root=pex_root)
        symlink_dir = None  # type: Optional[str]
        if os.path.islink(wheel_dir):
            symlink_dir = os.path.dirname(wheel_dir)
            wheel_dir = os.path.realpath(wheel_dir)
            wheel_hash_dir, _ = os.path.split(wheel_dir)
            wheel_hash = os.path.basename(wheel_hash_dir)

        return cls(
            path=wheel_dir,
            wheel_name=wheel_name,
            install_hash=install_hash,
            wheel_hash=wheel_hash,
            symlink_dir=symlink_dir,
        )

    def __init__(
        self,
        path,  # type: str
        wheel_name,  # type: str
        install_hash,  # type: str
        wheel_hash=None,  # type: Optional[str]
        symlink_dir=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        super(InstalledWheelDir, self).__init__(path)
        self.wheel_name = wheel_name
        self.install_hash = install_hash
        self.wheel_hash = wheel_hash
        self.symlink_dir = symlink_dir


class BootstrapDir(AtomicCacheDir):
    @classmethod
    def create(
        cls,
        bootstrap_hash,  # type: str
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        # type: (...) -> BootstrapDir
        bootstrap_dir = CacheDir.BOOTSTRAPS.path(bootstrap_hash, pex_root=pex_root)
        return cls(path=bootstrap_dir, bootstrap_hash=bootstrap_hash)

    def __init__(
        self,
        path,  # type: str
        bootstrap_hash,  # type: str
    ):
        # type: (...) -> None
        super(BootstrapDir, self).__init__(path)
        self.bootstrap_hash = bootstrap_hash


class UserCodeDir(AtomicCacheDir):
    @classmethod
    def create(
        cls,
        code_hash,  # type: str
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        # type: (...) -> UserCodeDir
        user_code_dir = CacheDir.USER_CODE.path(code_hash, pex_root=pex_root)
        return cls(path=user_code_dir, code_hash=code_hash)

    def __init__(
        self,
        path,  # type: str
        code_hash,  # type: str
    ):
        # type: (...) -> None
        super(UserCodeDir, self).__init__(path)
        self.code_hash = code_hash
