# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import os

from pex.common import safe_rmtree
from pex.compatibility import commonpath
from pex.enum import Enum
from pex.exceptions import production_assert
from pex.executables import is_exe
from pex.orderedset import OrderedSet
from pex.typing import TYPE_CHECKING, cast
from pex.variables import ENV, Variables

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, List, Optional, Type, TypeVar, Union

    from pex.dist_metadata import ProjectNameAndVersion
    from pex.interpreter import PythonInterpreter
    from pex.pep_440 import Version
    from pex.pep_503 import ProjectName
    from pex.pip.version import PipVersionValue
    from pex.targets import Target


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
        version=1,
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
        dependencies=[INSTALLED_WHEELS],
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
        version=1,
        name="Unzipped PEXes",
        description="The unzipped PEX files executed on this machine.",
        dependencies=[BOOTSTRAPS, USER_CODE, INSTALLED_WHEELS],
    )

    VENVS = Value(
        "venvs",
        version=1,
        name="Virtual Environments",
        description="Virtual environments generated at runtime for `--venv` mode PEXes.",
        dependencies=[INSTALLED_WHEELS],
    )


CacheDir.seal()

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
        return cls(path=unzip_dir, pex_hash=pex_hash, pex_root=pex_root)

    @classmethod
    def iter_all(cls, pex_root=ENV):
        # type: (Union[str, Variables]) -> Iterator[UnzipDir]
        for unzip_dir in glob.glob(CacheDir.UNZIPPED_PEXES.path("*", pex_root=pex_root)):
            if os.path.isdir(unzip_dir):
                pex_hash = os.path.basename(unzip_dir)
                yield UnzipDir(path=unzip_dir, pex_hash=pex_hash, pex_root=pex_root)

    def __init__(
        self,
        path,  # type: str
        pex_hash,  # type: str
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        # type: (...) -> None
        super(UnzipDir, self).__init__(path)
        self.pex_hash = pex_hash
        self._pex_root = pex_root

    def iter_deps(self):
        # type: () -> Iterator[Union[BootstrapDir, UserCodeDir, InstalledWheelDir]]

        from pex.pex_info import PexInfo

        pex_info = PexInfo.from_pex(self.path)
        if pex_info.bootstrap_hash:
            yield BootstrapDir.create(
                bootstrap_hash=pex_info.bootstrap_hash, pex_root=self._pex_root
            )
        if pex_info.code_hash:
            yield UserCodeDir.create(code_hash=pex_info.code_hash, pex_root=self._pex_root)
        for wheel_name, install_hash in pex_info.distributions.items():
            installed_wheel_dir = InstalledWheelDir.create(
                wheel_name=wheel_name, install_hash=install_hash, pex_root=self._pex_root
            )
            # N.B.: Not all installed wheels in a PEX's .deps will be extracted for a given
            # interpreter if the PEX is multiplatform.
            if os.path.exists(installed_wheel_dir):
                yield installed_wheel_dir


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

    def iter_deps(self):
        # type: () -> Iterator[InstalledWheelDir]

        from pex.pex_info import PexInfo

        pex_info = PexInfo.from_pex(self.path)
        if not pex_info.venv_site_packages_copies:
            for wheel_name, install_hash in pex_info.distributions.items():
                installed_wheel_dir = InstalledWheelDir.create(
                    wheel_name=wheel_name, install_hash=install_hash, pex_root=self._pex_root
                )
                # N.B.: Not all installed wheels in a PEX's .deps will be installed in a given
                # venv if the PEX is multiplatform.
                if os.path.exists(installed_wheel_dir):
                    yield installed_wheel_dir


class InstalledWheelDir(AtomicCacheDir):
    @classmethod
    def iter_all(cls, pex_root=ENV):
        # type: (Union[str, Variables]) -> Iterator[InstalledWheelDir]

        from pex.dist_metadata import ProjectNameAndVersion

        symlinks = []  # type: List[str]
        dirs = OrderedSet()  # type: OrderedSet[str]
        for path in glob.glob(CacheDir.INSTALLED_WHEELS.path("*", "*.whl", pex_root=pex_root)):
            if not os.path.isdir(path):
                continue
            if os.path.islink(path):
                symlinks.append(path)
            else:
                dirs.add(path)

        for symlink in symlinks:
            wheel_dir = os.path.realpath(symlink)
            dirs.discard(wheel_dir)
            wheel_hash = os.path.basename(os.path.dirname(wheel_dir))
            symlink_dir = os.path.dirname(symlink)
            install_hash = os.path.basename(symlink_dir)
            wheel_name = os.path.basename(wheel_dir)
            pnav = ProjectNameAndVersion.from_filename(wheel_name)
            yield InstalledWheelDir(
                wheel_dir,
                wheel_name=wheel_name,
                project_name=pnav.canonicalized_project_name,
                version=pnav.canonicalized_version,
                install_hash=install_hash,
                wheel_hash=wheel_hash,
                symlink_dir=symlink_dir,
            )
        for wheel_dir in dirs:
            install_hash = os.path.basename(os.path.dirname(wheel_dir))
            wheel_name = os.path.basename(wheel_dir)
            pnav = ProjectNameAndVersion.from_filename(wheel_name)
            yield InstalledWheelDir(
                wheel_dir,
                wheel_name=wheel_name,
                project_name=pnav.canonicalized_project_name,
                version=pnav.canonicalized_version,
                install_hash=install_hash,
            )

    @classmethod
    def create(
        cls,
        wheel_name,  # type: str
        install_hash,  # type: str
        wheel_hash=None,  # type: Optional[str]
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        # type: (...) -> InstalledWheelDir

        from pex.dist_metadata import ProjectNameAndVersion

        pnav = ProjectNameAndVersion.from_filename(wheel_name)
        wheel_dir = CacheDir.INSTALLED_WHEELS.path(install_hash, wheel_name, pex_root=pex_root)
        symlink_dir = None  # type: Optional[str]
        if os.path.islink(wheel_dir):
            symlink_dir = os.path.dirname(wheel_dir)
            wheel_dir = os.path.realpath(wheel_dir)
            recorded_wheel_hash = os.path.basename(os.path.dirname(wheel_dir))
            if wheel_hash:
                production_assert(wheel_hash == recorded_wheel_hash)
            else:
                wheel_hash = recorded_wheel_hash
        elif wheel_hash is not None:
            symlink_dir = os.path.dirname(wheel_dir)
            wheel_dir = CacheDir.INSTALLED_WHEELS.path(wheel_hash, wheel_name, pex_root=pex_root)

        return cls(
            path=wheel_dir,
            wheel_name=wheel_name,
            project_name=pnav.canonicalized_project_name,
            version=pnav.canonicalized_version,
            install_hash=install_hash,
            wheel_hash=wheel_hash,
            symlink_dir=symlink_dir,
        )

    def __init__(
        self,
        path,  # type: str
        wheel_name,  # type: str
        project_name,  # type: ProjectName
        version,  # type: Version
        install_hash,  # type: str
        wheel_hash=None,  # type: Optional[str]
        symlink_dir=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        super(InstalledWheelDir, self).__init__(path)
        self.wheel_name = wheel_name
        self.project_name = project_name
        self.version = version
        self.install_hash = install_hash
        self.wheel_hash = wheel_hash
        self.symlink_dir = symlink_dir


class BootstrapDir(AtomicCacheDir):
    @classmethod
    def iter_all(cls, pex_root=ENV):
        # type: (Union[str, Variables]) -> Iterator[BootstrapDir]

        for path in glob.glob(CacheDir.BOOTSTRAPS.path("*", pex_root=pex_root)):
            bootstrap_hash = os.path.basename(path)
            yield cls(path=path, bootstrap_hash=bootstrap_hash)

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
    def iter_all(cls, pex_root=ENV):
        # type: (Union[str, Variables]) -> Iterator[UserCodeDir]

        for path in glob.glob(CacheDir.USER_CODE.path("*", pex_root=pex_root)):
            code_hash = os.path.basename(path)
            yield cls(path=path, code_hash=code_hash)

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


class PipPexDir(AtomicCacheDir):
    @classmethod
    def iter_all(cls, pex_root=ENV):
        # type: (Union[str, Variables]) -> Iterator[PipPexDir]

        from pex.pip.version import PipVersion

        for base_dir in glob.glob(CacheDir.PIP.path("*", pex_root=pex_root)):
            version = PipVersion.for_value(os.path.basename(base_dir))
            cache_dir = os.path.join(base_dir, "pip_cache")
            for pex_dir in glob.glob(os.path.join(base_dir, "pip.pex", "*", "*")):
                yield cls(path=pex_dir, version=version, base_dir=base_dir, cache_dir=cache_dir)

    @classmethod
    def create(
        cls,
        version,  # type: PipVersionValue
        fingerprint,  # type: str
    ):
        # type: (...) -> PipPexDir

        from pex.third_party import isolated

        base_dir = CacheDir.PIP.path(str(version))
        return cls(
            path=os.path.join(base_dir, "pip.pex", isolated().pex_hash, fingerprint),
            version=version,
            base_dir=base_dir,
            cache_dir=os.path.join(base_dir, "pip_cache"),
        )

    def __init__(
        self,
        path,  # type: str
        version,  # type: PipVersionValue
        base_dir,  # type: str
        cache_dir,  # type: str
    ):
        # type: (...) -> None
        super(PipPexDir, self).__init__(path)
        self.version = version
        self.base_dir = base_dir
        self.cache_dir = cache_dir


class DownloadDir(AtomicCacheDir):
    @classmethod
    def iter_all(cls, pex_root=ENV):
        # type: (Union[str, Variables]) -> Iterator[DownloadDir]

        from pex.dist_metadata import is_sdist, is_wheel

        for file_path in glob.glob(CacheDir.DOWNLOADS.path("*", "*", pex_root=pex_root)):
            if os.path.isdir(file_path):
                continue
            if not is_sdist(file_path) and not is_wheel(file_path):
                continue
            download_dir, file_name = os.path.split(file_path)
            yield cls(path=download_dir, file_name=file_name)

    @classmethod
    def create(
        cls,
        file_hash,  # type: str
        file_name=None,  # type: Optional[str]
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        # type: (...) -> DownloadDir
        return cls(path=CacheDir.DOWNLOADS.path(file_hash, pex_root=pex_root), file_name=file_name)

    def __init__(
        self,
        path,  # type: str
        file_name=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        super(DownloadDir, self).__init__(path)
        self._file_name = file_name
        self.__pnav = None  # type: Optional[ProjectNameAndVersion]

    @property
    def file_name(self):
        # type: () -> str
        from pex.dist_metadata import is_sdist, is_wheel

        if self._file_name is None:
            potential_file_names = [
                file_name
                for file_name in os.listdir(self.path)
                if not os.path.isdir(os.path.join(self.path, file_name))
                and (is_sdist(file_name) or is_wheel(file_name))
            ]
            production_assert(len(potential_file_names) == 1)
            self._file_name = potential_file_names[0]
        return self._file_name

    @property
    def _pnav(self):
        # type: () -> ProjectNameAndVersion
        if self.__pnav is None:
            from pex.dist_metadata import ProjectNameAndVersion

            self.__pnav = ProjectNameAndVersion.from_filename(self.file_name)
        return self.__pnav

    @property
    def project_name(self):
        # type: () -> ProjectName
        return self._pnav.canonicalized_project_name

    @property
    def version(self):
        # type: () -> Version
        return self._pnav.canonicalized_version


class BuiltWheelDir(AtomicCacheDir):
    @classmethod
    def iter_all(cls, pex_root=ENV):
        # type: (Union[str, Variables]) -> Iterator[BuiltWheelDir]

        from pex.dist_metadata import ProjectNameAndVersion, UnrecognizedDistributionFormat

        for path in glob.glob(CacheDir.BUILT_WHEELS.path("sdists", "*", "*")):
            sdist, fingerprint = os.path.split(path)
            try:
                pnav = ProjectNameAndVersion.from_filename(sdist)
                yield BuiltWheelDir.create(
                    sdist=sdist, fingerprint=fingerprint, pnav=pnav, pex_root=pex_root
                )
            except UnrecognizedDistributionFormat:
                # This is a source distribution that does not follow sdist naming patterns / is not
                # distributed via PyPI; e.g.: a GitHub source tarball or zip.
                for built_wheel in glob.glob(os.path.join(path, "*", "*")):
                    file_name = os.path.basename(built_wheel)
                    dist_dir = os.path.dirname(built_wheel)
                    yield BuiltWheelDir(path=dist_dir, dist_dir=dist_dir, file_name=file_name)

        for built_wheel in glob.glob(
            CacheDir.BUILT_WHEELS.path("local_projects", "*", "*", "*", "*")
        ):
            file_name = os.path.basename(built_wheel)
            dist_dir = os.path.dirname(built_wheel)
            yield BuiltWheelDir(path=dist_dir, dist_dir=dist_dir, file_name=file_name)

    @classmethod
    def create(
        cls,
        sdist,  # type: str
        fingerprint=None,  # type: Optional[str]
        pnav=None,  # type: Optional[ProjectNameAndVersion]
        target=None,  # type: Optional[Target]
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        # type: (...) -> BuiltWheelDir

        import hashlib

        from pex import targets
        from pex.dist_metadata import is_sdist
        from pex.util import CacheHelper

        if is_sdist(sdist):
            dist_type = "sdists"
            fingerprint = fingerprint or CacheHelper.hash(sdist, hasher=hashlib.sha256)
            file_name = os.path.basename(sdist)
        else:
            dist_type = "local_projects"
            fingerprint = fingerprint or CacheHelper.dir_hash(sdist, hasher=hashlib.sha256)
            file_name = None

        # For the purposes of building a wheel from source, the product should be uniqued by the
        # wheel name which is unique on the host os up to the python and abi tags. In other words,
        # the product of a CPython 2.7.6 wheel build and a CPython 2.7.18 wheel build should be
        # functionally interchangeable if the two CPython interpreters have matching abis.
        #
        # However, this is foiled by at least two scenarios:
        # 1. Running a vm / container with shared storage mounted. This can introduce a different
        #    platform on the host.
        # 2. On macOS the same host can report / use different OS versions (c.f.: the
        #    MACOSX_DEPLOYMENT_TARGET environment variable and the 10.16 / 11.0 macOS Big Sur
        #    transitional case in particular).
        #
        # As such, we must be pessimistic and assume the wheel will be platform specific to the
        # full extent possible.
        interpreter = (target or targets.current()).get_interpreter()
        target_tags = "{python_tag}-{abi_tag}-{platform_tag}".format(
            python_tag=interpreter.identity.python_tag,
            abi_tag=interpreter.identity.abi_tag,
            platform_tag=interpreter.identity.platform_tag,
        )
        sdist_dir = CacheDir.BUILT_WHEELS.path(
            dist_type, os.path.basename(sdist), pex_root=pex_root
        )
        dist_dir = os.path.join(sdist_dir, fingerprint, target_tags)

        if is_sdist(sdist):
            return cls(path=sdist_dir, dist_dir=dist_dir, file_name=file_name, pnav=pnav)
        else:
            return cls(path=dist_dir, dist_dir=dist_dir, file_name=file_name, pnav=pnav)

    def __init__(
        self,
        path,  # type: str
        dist_dir,  # type: str
        file_name=None,  # type: Optional[str]
        pnav=None,  # type: Optional[ProjectNameAndVersion]
    ):
        # type: (...) -> None
        super(BuiltWheelDir, self).__init__(path)
        self.dist_dir = dist_dir
        self._file_name = file_name
        self.__pnav = pnav

    @property
    def file_name(self):
        # type: () -> str
        from pex.dist_metadata import is_wheel

        if self._file_name is None:
            potential_file_names = [
                file_name
                for file_name in os.listdir(self.dist_dir)
                if not os.path.isdir(os.path.join(self.dist_dir, file_name)) and is_wheel(file_name)
            ]
            production_assert(len(potential_file_names) == 1)
            self._file_name = potential_file_names[0]
        return self._file_name

    @property
    def _pnav(self):
        # type: () -> ProjectNameAndVersion
        if self.__pnav is None:
            from pex.dist_metadata import ProjectNameAndVersion

            self.__pnav = ProjectNameAndVersion.from_filename(self.file_name)
        return self.__pnav

    @property
    def project_name(self):
        # type: () -> ProjectName
        return self._pnav.canonicalized_project_name

    @property
    def version(self):
        # type: () -> Version
        return self._pnav.canonicalized_version


class InterpreterDir(AtomicCacheDir):
    INTERP_INFO_FILE = "INTERP-INFO"

    @classmethod
    def iter_all(cls, pex_root=ENV):
        # type: (Union[str, Variables]) -> Iterator[InterpreterDir]

        for interp_info_file in glob.glob(
            CacheDir.INTERPRETERS.path("*", "*", "*", cls.INTERP_INFO_FILE, pex_root=pex_root)
        ):
            yield cls(path=os.path.dirname(interp_info_file), interp_info_file=interp_info_file)

    @classmethod
    def create(cls, binary):
        # type: (str) -> InterpreterDir

        import hashlib
        import platform

        from pex.tracer import TRACER
        from pex.util import CacheHelper

        # Part of the PythonInterpreter data are environment markers that depend on the current OS
        # release. That data can change when the OS is upgraded but (some of) the installed
        # interpreters remain the same. As such, include the OS in the hash structure for cached
        # interpreters.
        os_digest = hashlib.sha1()
        for os_identifier in platform.release(), platform.version():
            os_digest.update(os_identifier.encode("utf-8"))
        os_hash = os_digest.hexdigest()

        interpreter_cache_dir = CacheDir.INTERPRETERS.path()
        os_cache_dir = os.path.join(interpreter_cache_dir, os_hash)
        if os.path.isdir(interpreter_cache_dir) and not os.path.isdir(os_cache_dir):
            with TRACER.timed("GCing interpreter cache from prior OS version"):
                safe_rmtree(interpreter_cache_dir)

        interpreter_hash = CacheHelper.hash(binary)

        # Some distributions include more than one copy of the same interpreter via a hard link
        # (e.g.: python3.7 is a hardlink to python3.7m). To ensure a deterministic INTERP-INFO file
        # we must emit a separate INTERP-INFO for each link since INTERP-INFO contains the
        # interpreter path and would otherwise be unstable.
        #
        # See PythonInterpreter._REGEXEN for a related affordance.
        #
        # N.B.: The path for --venv mode interpreters can be quite long; so we just used a fixed
        # length hash of the interpreter binary path to ensure uniqueness and not run afoul of file
        # name length limits.
        path_id = hashlib.sha1(binary.encode("utf-8")).hexdigest()

        cache_dir = os.path.join(os_cache_dir, interpreter_hash, path_id)
        cache_file = os.path.join(cache_dir, cls.INTERP_INFO_FILE)

        return cls(path=cache_dir, interp_info_file=cache_file)

    def __init__(
        self,
        path,  # type: str
        interp_info_file,  # type: str
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        # type: (...) -> None
        super(InterpreterDir, self).__init__(path)
        self.interp_info_file = interp_info_file
        self._interpreter = None  # type: Optional[PythonInterpreter]
        self._pex_root = pex_root

    @property
    def interpreter(self):
        # type: () -> PythonInterpreter
        if self._interpreter is None:
            with open(self.interp_info_file) as fp:
                from pex.interpreter import PythonIdentity, PythonInterpreter

                self._interpreter = PythonInterpreter(PythonIdentity.decode(fp.read()))
        return self._interpreter

    def valid(self):
        # type: () -> bool
        return is_exe(self.interpreter.binary)

    def venv_dir(self):
        # type: () -> Optional[VenvDir]

        if not self.interpreter.is_venv:
            return None
        cached_venv_root = CacheDir.VENVS.path()
        if cached_venv_root != commonpath((cached_venv_root, self.interpreter.prefix)):
            return None
        head, contents_hash = os.path.split(self.interpreter.prefix)
        pex_hash = os.path.basename(head)
        return VenvDir.create(
            pex_hash=pex_hash, contents_hash=contents_hash, pex_root=self._pex_root
        )
