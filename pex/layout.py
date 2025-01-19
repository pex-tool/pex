# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import zipfile
from abc import abstractmethod
from contextlib import contextmanager

from pex.atomic_directory import atomic_directory
from pex.cache import access as cache_access
from pex.cache.dirs import BootstrapDir, InstalledWheelDir, UserCodeDir
from pex.common import ZipFileEx, open_zip, safe_copy, safe_mkdir, safe_mkdtemp
from pex.enum import Enum
from pex.executables import is_script
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.variables import ENV, unzip_dir

if TYPE_CHECKING:
    from types import TracebackType
    from typing import Any, Dict, Iterator, Optional, Text, Tuple, Type

    from pex.pex_info import PexInfo


BOOTSTRAP_DIR = ".bootstrap"
DEPS_DIR = ".deps"
PEX_INFO_PATH = "PEX-INFO"
PEX_LAYOUT_PATH = "PEX-LAYOUT"


class Layout(Enum["Layout.Value"]):
    class Value(Enum.Value):
        @classmethod
        def try_load(cls, pex_directory):
            # type: (str) -> Optional[Layout.Value]
            layout = os.path.join(pex_directory, PEX_LAYOUT_PATH)
            if not os.path.isfile(layout):
                return None
            with open(layout) as fp:
                return Layout.for_value(fp.read().strip())

        def record(self, pex_directory):
            # type: (str) -> None
            with open(os.path.join(pex_directory, PEX_LAYOUT_PATH), "w") as fp:
                fp.write(self.value)

    ZIPAPP = Value("zipapp")
    PACKED = Value("packed")
    LOOSE = Value("loose")

    @classmethod
    def identify(cls, pex):
        # type: (str) -> Layout.Value
        """Assumes pex is a valid PEX and identifies its layout."""
        if zipfile.is_zipfile(pex) and is_script(
            pex,
            # N.B.: A PEX file need not be executable since it can always be run via `python a.pex`.
            check_executable=False,
        ):
            return cls.ZIPAPP

        if os.path.isdir(pex) and zipfile.is_zipfile(os.path.join(pex, BOOTSTRAP_DIR)):
            return cls.PACKED

        return cls.LOOSE

    @classmethod
    def identify_original(cls, pex):
        # type: (str) -> Layout.Value
        layout = cls.identify(pex)
        if layout is not Layout.LOOSE:
            return layout
        return cls.Value.try_load(pex) or Layout.LOOSE


Layout.seal()


class _Layout(object):
    def __init__(
        self,
        layout,  # type: Layout.Value
        path,  # type: str
    ):
        # type: (...) -> None
        self._layout = layout
        self._path = os.path.normpath(path)

    @property
    def type(self):
        # type: () -> Layout.Value
        return self._layout

    @property
    def path(self):
        # type: () -> str
        return self._path

    def bootstrap_strip_prefix(self):
        # type: () -> Optional[str]
        return None

    @abstractmethod
    def extract_bootstrap(self, dest_dir):
        # type: (str) -> None
        raise NotImplementedError()

    def dist_strip_prefix(self, dist_name):
        # type: (str) -> Optional[str]
        return None

    @abstractmethod
    def dist_size(
        self,
        dist_relpath,  # type: str
        is_wheel_file,  # type: bool
    ):
        # type: (...) -> int
        raise NotImplementedError()

    @abstractmethod
    def extract_dist(
        self,
        dest_dir,  # type: str
        dist_relpath,  # type: str
        is_wheel_file,  # type: bool
    ):
        # type: (...) -> None
        raise NotImplementedError()

    @abstractmethod
    def wheel_file_path(self, dist_relpath):
        # type: (str) -> str
        raise NotImplementedError()

    @abstractmethod
    def extract_code(self, dest_dir):
        # type: (str) -> None
        raise NotImplementedError()

    @abstractmethod
    def extract_pex_info(self, dest_dir):
        # type: (str) -> None
        raise NotImplementedError()

    @abstractmethod
    def extract_main(self, dest_dir):
        # type: (str) -> None
        raise NotImplementedError()

    @abstractmethod
    def extract_import_hook(self, dest_dir):
        # type: (str) -> None
        raise NotImplementedError()

    def record(self, dest_dir):
        # type: (str) -> None
        self._layout.record(dest_dir)


def _install_distribution(
    distribution_info,  # type: Tuple[str, str]
    layout,  # type: _Layout
    pex_info,  # type: PexInfo
    work_dir,  # type: str
    install_to,  # type: str
):
    # type: (...) -> str

    location, sha = distribution_info
    is_wheel_file = pex_info.deps_are_wheel_files
    spread_dest = InstalledWheelDir.create(
        wheel_name=location, install_hash=sha, pex_root=pex_info.pex_root
    )
    dist_relpath = os.path.join(DEPS_DIR, location)
    source = None if is_wheel_file else layout.dist_strip_prefix(location)
    symlink_src = os.path.relpath(
        spread_dest,
        os.path.join(install_to, os.path.dirname(dist_relpath)),
    )
    symlink_dest = os.path.join(work_dir, dist_relpath)

    with atomic_directory(spread_dest, source=source) as spread_chroot:
        if not spread_chroot.is_finalized():
            layout.extract_dist(
                dest_dir=spread_chroot.work_dir,
                dist_relpath=dist_relpath,
                is_wheel_file=is_wheel_file,
            )

    safe_mkdir(os.path.dirname(symlink_dest))
    os.symlink(symlink_src, symlink_dest)
    return location


def _ensure_distributions_installed_serial(
    layout,  # type: _Layout
    pex_info,  # type: PexInfo
    work_dir,  # type: str
    install_to,  # type: str
):
    # type: (...) -> None

    for item in pex_info.distributions.items():
        with TRACER.timed("Installing {wheel}".format(wheel=item[0]), V=2):
            _install_distribution(item, layout, pex_info, work_dir, install_to)


def _ensure_distributions_installed_parallel(
    layout,  # type: _Layout
    pex_info,  # type: PexInfo
    work_dir,  # type: str
    install_to,  # type: str
    max_jobs,  # type: int
):
    # type: (...) -> None

    import functools

    from pex.jobs import map_parallel

    install_distribution = functools.partial(
        _install_distribution,
        layout=layout,
        pex_info=pex_info,
        work_dir=work_dir,
        install_to=install_to,
    )

    map_parallel(
        inputs=pex_info.distributions.items(),
        function=install_distribution,
        noun="wheel",
        verb="install",
        verb_past="installed",
        max_jobs=max_jobs,
        costing_function=lambda item: layout.dist_size(
            os.path.join(DEPS_DIR, item[0]), is_wheel_file=pex_info.deps_are_wheel_files
        ),
    )


# This value was found via experiment on a single laptop with 16 cores and SSD storage. The
# threshold that needs to be overcome is the startup and communication overhead of a Python
# multiprocessing pool. It's completely unclear this is a good value in general let alone the
# heuristic using it is reasonable; as such the user-facing documentation makes it clear the
# heuristic can be tweaked from release to release in order to try to improve performance.
AVERAGE_DISTRIBUTION_SIZE_PARALLEL_JOB_THRESHOLD = 1 * 1024 * 1024  # ~1MB


def _ensure_distributions_installed(
    layout,  # type: _Layout
    pex_info,  # type: PexInfo
    work_dir,  # type: str
    install_to,  # type: str
):
    # type: (...) -> None

    dist_count = len(pex_info.distributions)
    if dist_count == 0:
        return

    install_serial = dist_count == 1 or pex_info.max_install_jobs == 1
    if not install_serial and pex_info.max_install_jobs == -1:
        total_size = sum(
            layout.dist_size(os.path.join(DEPS_DIR, location), pex_info.deps_are_wheel_files)
            for location in pex_info.distributions
        )
        average_distribution_size = total_size // dist_count
        install_serial = (
            average_distribution_size < AVERAGE_DISTRIBUTION_SIZE_PARALLEL_JOB_THRESHOLD
        )
        if install_serial:
            TRACER.log(
                "Installing {count} distributions in serial based on average distribution "
                "size of {avg_size} bytes".format(
                    count=dist_count, avg_size=average_distribution_size
                )
            )
        else:
            TRACER.log(
                "Installing {count} distributions in parallel based on average distribution "
                "size of {avg_size} bytes".format(
                    count=dist_count, avg_size=average_distribution_size
                )
            )

    if install_serial:
        _ensure_distributions_installed_serial(
            layout=layout, pex_info=pex_info, work_dir=work_dir, install_to=install_to
        )
    else:
        max_jobs = 0 if pex_info.max_install_jobs == -1 else pex_info.max_install_jobs
        _ensure_distributions_installed_parallel(
            layout=layout,
            pex_info=pex_info,
            work_dir=work_dir,
            install_to=install_to,
            max_jobs=max_jobs,
        )


def _ensure_installed(
    layout,  # type: _Layout
    pex_root,  # type: str
    pex_hash,  # type: str
):
    # type: (...) -> str
    if layout.type is Layout.LOOSE:
        from pex.pex_info import PexInfo

        pex_info = PexInfo.from_pex(layout.path)
        if not pex_info.distributions or not pex_info.deps_are_wheel_files:
            # A loose PEX with no dependencies or dependencies that are pre-installed wheel chroots
            # is in the canonical form of a PEX executable zipapp already and needs no install.
            return layout.path

    with TRACER.timed("Laying out {}".format(layout)):
        pex = layout.path
        install_to = unzip_dir(pex_root=pex_root, pex_hash=pex_hash)
        if not os.path.exists(install_to):
            with ENV.patch(PEX_ROOT=pex_root):
                cache_access.read_write()
        with atomic_directory(install_to) as chroot:
            if not chroot.is_finalized():
                with ENV.patch(PEX_ROOT=pex_root), TRACER.timed(
                    "Installing {} to {}".format(pex, install_to)
                ):
                    from pex.pex_info import PexInfo

                    pex_info = PexInfo.from_pex(pex)
                    pex_info.update(PexInfo.from_env())

                    if pex_info.bootstrap_hash is None:
                        raise AssertionError(
                            "Expected bootstrap_cache to be populated for {}.".format(layout)
                        )
                    bootstrap_cache = BootstrapDir.create(
                        pex_info.bootstrap_hash, pex_root=pex_info.pex_root
                    )
                    if pex_info.code_hash is None:
                        raise AssertionError(
                            "Expected code_hash to be populated for {}.".format(layout)
                        )
                    code_cache = UserCodeDir.create(pex_info.code_hash, pex_root=pex_info.pex_root)

                    with atomic_directory(
                        bootstrap_cache, source=layout.bootstrap_strip_prefix()
                    ) as bootstrap_zip_chroot:
                        if not bootstrap_zip_chroot.is_finalized():
                            layout.extract_bootstrap(bootstrap_zip_chroot.work_dir)
                    os.symlink(
                        os.path.join(os.path.relpath(bootstrap_cache, install_to)),
                        os.path.join(chroot.work_dir, BOOTSTRAP_DIR),
                    )

                    _ensure_distributions_installed(
                        layout=layout,
                        pex_info=pex_info,
                        work_dir=chroot.work_dir,
                        install_to=install_to,
                    )

                    with atomic_directory(code_cache) as code_chroot:
                        if not code_chroot.is_finalized():
                            layout.extract_code(code_chroot.work_dir)
                    for path in os.listdir(code_cache):
                        os.symlink(
                            os.path.join(os.path.relpath(code_cache, install_to), path),
                            os.path.join(chroot.work_dir, path),
                        )

                    layout.extract_pex_info(chroot.work_dir)
                    layout.extract_main(chroot.work_dir)
                    layout.record(chroot.work_dir)
        cache_access.record_access(install_to)
        return install_to


class _ZipAppPEX(_Layout):
    def __init__(
        self,
        path,  # type: str
    ):
        # type: (...) -> None
        super(_ZipAppPEX, self).__init__(Layout.ZIPAPP, path)
        self._zfp = None  # type: Optional[zipfile.ZipFile]
        self._names = None  # type: Optional[Tuple[Text, ...]]

    def close(self):
        # type: () -> None
        if self._zfp is not None:
            self._zfp.close()

    def open(self):
        # type: () -> zipfile.ZipFile
        if self._zfp is None:
            self._zfp = ZipFileEx(self.path)
        return self._zfp

    def __getstate__(self):
        # type: () -> Dict[str, Any]
        state = self.__dict__.copy()
        # We can't pickle an open file handle; so don't try.
        state["_zfp"] = None
        return state

    def __enter__(self):
        # type: () -> _ZipAppPEX
        self.open()
        return self

    def __exit__(
        self,
        _exc_type,  # type: Optional[Type]
        _exc_val,  # type: Optional[Any]
        _exc_tb,  # type: Optional[TracebackType]
    ):
        # type: (...) -> None
        self.close()

    def __del__(self):
        # type: () -> None
        self.close()

    @property
    def zfp(self):
        # type: () -> zipfile.ZipFile
        return self.open()

    @property
    def names(self):
        # type: () -> Tuple[Text, ...]
        if self._names is None:
            self._names = tuple(self.zfp.namelist())
        return self._names

    def bootstrap_strip_prefix(self):
        # type: () -> Optional[str]
        return BOOTSTRAP_DIR

    def extract_bootstrap(self, dest_dir):
        # type: (str) -> None
        for name in self.names:
            if name.startswith(BOOTSTRAP_DIR) and not name.endswith("/"):
                self.zfp.extract(name, dest_dir)

    def dist_strip_prefix(self, dist_name):
        # type: (str) -> Optional[str]
        return os.path.join(DEPS_DIR, dist_name)

    def dist_size(
        self,
        dist_relpath,  # type: str
        is_wheel_file,  # type: bool
    ):
        # type: (...) -> int
        if is_wheel_file:
            return self.zfp.getinfo(dist_relpath).file_size
        else:
            return sum(
                self.zfp.getinfo(name).file_size
                for name in self.names
                if name.startswith(dist_relpath)
            )

    def extract_dist(
        self,
        dest_dir,  # type: str
        dist_relpath,  # type: str
        is_wheel_file,  # type: bool
    ):
        # type: (...) -> None
        if is_wheel_file:
            from pex.pep_427 import install_wheel_chroot

            install_wheel_chroot(self.wheel_file_path(dist_relpath), dest_dir)
        else:
            for name in self.names:
                if name.startswith(dist_relpath) and not name.endswith("/"):
                    self.zfp.extract(name, dest_dir)

    def wheel_file_path(self, dist_relpath):
        # type: (str) -> str
        extract_chroot = safe_mkdtemp()
        self.zfp.extract(dist_relpath, extract_chroot)
        return os.path.join(extract_chroot, dist_relpath)

    def extract_code(self, dest_dir):
        # type: (str) -> None
        for name in self.names:
            if name not in ("__main__.py", PEX_INFO_PATH) and not name.startswith(
                ("__pex__", BOOTSTRAP_DIR, DEPS_DIR)
            ):
                self.zfp.extract(name, dest_dir)

    def extract_pex_info(self, dest_dir):
        # type: (str) -> None
        self.zfp.extract(PEX_INFO_PATH, dest_dir)

    def extract_main(self, dest_dir):
        # type: (str) -> None
        self.zfp.extract("__main__.py", dest_dir)

    def extract_import_hook(self, dest_dir):
        # type: (str) -> None
        self.zfp.extract("__pex__/__init__.py", dest_dir)

    def __str__(self):
        return "PEX zipfile {}".format(self.path)


class _PackedPEX(_Layout):
    def __init__(self, path):
        # type: (str) -> None
        super(_PackedPEX, self).__init__(Layout.PACKED, path)

    def extract_bootstrap(self, dest_dir):
        # type: (str) -> None
        with open_zip(os.path.join(self._path, BOOTSTRAP_DIR)) as zfp:
            zfp.extractall(dest_dir)

    def dist_size(
        self,
        dist_relpath,  # type: str
        is_wheel_file,  # type: bool
    ):
        # type: (...) -> int
        return os.path.getsize(os.path.join(self._path, dist_relpath))

    def extract_dist(
        self,
        dest_dir,  # type: str
        dist_relpath,  # type: str
        is_wheel_file,  # type: bool
    ):
        # type: (...) -> None
        dist_path = self.wheel_file_path(dist_relpath)
        if is_wheel_file:
            from pex.pep_427 import install_wheel_chroot

            with TRACER.timed("Installing wheel file {}".format(dist_relpath)):
                install_wheel_chroot(dist_path, dest_dir)
        else:
            with TRACER.timed("Installing zipped wheel install {}".format(dist_relpath)):
                with open_zip(dist_path) as zfp:
                    zfp.extractall(dest_dir)

    def wheel_file_path(self, dist_relpath):
        # type: (str) -> str
        return os.path.join(self._path, dist_relpath)

    def extract_code(self, dest_dir):
        # type: (str) -> None
        for root, dirs, files in os.walk(self._path):
            rel_root = os.path.relpath(root, self._path)
            if root == self._path:
                dirs[:] = [d for d in dirs if d not in ("__pex__", DEPS_DIR)]
                files[:] = [
                    f
                    for f in files
                    if f not in ("__main__.py", "pex", PEX_INFO_PATH, BOOTSTRAP_DIR)
                ]
            for d in dirs:
                safe_mkdir(os.path.join(dest_dir, rel_root, d))
            for f in files:
                safe_copy(
                    os.path.join(root, f),
                    os.path.join(dest_dir, rel_root, f),
                )

    def extract_pex_info(self, dest_dir):
        # type: (str) -> None
        safe_copy(os.path.join(self._path, PEX_INFO_PATH), os.path.join(dest_dir, PEX_INFO_PATH))

    def extract_main(self, dest_dir):
        # type: (str) -> None
        safe_copy(os.path.join(self._path, "__main__.py"), os.path.join(dest_dir, "__main__.py"))

    def extract_import_hook(self, dest_dir):
        # type: (str) -> None
        dest = os.path.join(dest_dir, "__pex__", "__init__.py")
        safe_mkdir(os.path.dirname(dest))
        safe_copy(os.path.join(self._path, "__pex__", "__init__.py"), dest)

    def __str__(self):
        return "Spread PEX directory {}".format(self._path)


class _LoosePEX(_Layout):
    def __init__(self, path):
        super(_LoosePEX, self).__init__(Layout.LOOSE, path)

    def extract_bootstrap(self, dest_dir):
        # type: (str) -> None
        bootstrap_dir = os.path.join(self._path, BOOTSTRAP_DIR)
        for root, dirs, files in os.walk(bootstrap_dir):
            rel_root = os.path.relpath(root, bootstrap_dir)
            for d in dirs:
                safe_mkdir(os.path.join(dest_dir, rel_root, d))
            for f in files:
                safe_copy(os.path.join(root, f), os.path.join(dest_dir, rel_root, f))

    def dist_size(
        self,
        dist_relpath,  # type: str
        is_wheel_file,  # type: bool
    ):
        assert (
            is_wheel_file
        ), "Expected loose layout install to be skipped when deps are pre-installed wheel chroots."
        return os.path.getsize(os.path.join(self._path, dist_relpath))

    def extract_dist(
        self,
        dest_dir,
        dist_relpath,  # type: str
        is_wheel_file,  # type: bool
    ):
        assert (
            is_wheel_file
        ), "Expected loose layout install to be skipped when deps are pre-installed wheel chroots."
        from pex.pep_427 import install_wheel_chroot

        with TRACER.timed("Installing wheel file {}".format(dist_relpath)):
            install_wheel_chroot(self.wheel_file_path(dist_relpath), dest_dir)

    def wheel_file_path(self, dist_relpath):
        # type: (str) -> str
        return os.path.join(self._path, dist_relpath)

    def extract_code(self, dest_dir):
        # type: (str) -> None
        for root, dirs, files in os.walk(self._path):
            rel_root = os.path.relpath(root, self._path)
            if root == self._path:
                dirs[:] = [d for d in dirs if d not in ("__pex__", DEPS_DIR, BOOTSTRAP_DIR)]
                files[:] = [f for f in files if f not in ("__main__.py", "pex", PEX_INFO_PATH)]
            for d in dirs:
                safe_mkdir(os.path.join(dest_dir, rel_root, d))
            for f in files:
                safe_copy(
                    os.path.join(root, f),
                    os.path.join(dest_dir, rel_root, f),
                )

    def extract_pex_info(self, dest_dir):
        # type: (str) -> None
        safe_copy(os.path.join(self._path, PEX_INFO_PATH), os.path.join(dest_dir, PEX_INFO_PATH))

    def extract_main(self, dest_dir):
        # type: (str) -> None
        safe_copy(os.path.join(self._path, "__main__.py"), os.path.join(dest_dir, "__main__.py"))

    def extract_import_hook(self, dest_dir):
        # type: (str) -> None
        dest = os.path.join(dest_dir, "__pex__", "__init__.py")
        safe_mkdir(os.path.dirname(dest))
        safe_copy(os.path.join(self._path, "__pex__", "__init__.py"), dest)

    def __str__(self):
        return "Loose PEX directory {}".format(self._path)


@contextmanager
def identify_layout(pex):
    # type: (str) -> Iterator[_Layout]

    layout = Layout.identify(pex)
    if Layout.ZIPAPP is layout:
        with _ZipAppPEX(pex) as zip_app_pex:
            yield zip_app_pex
    elif Layout.PACKED is layout:
        yield _PackedPEX(pex)
    elif Layout.LOOSE is layout:
        yield _LoosePEX(pex)
    else:
        raise AssertionError("Un-handled PEX layout type: {layout}".format(layout=layout))


def ensure_installed(
    pex,  # type: str
    pex_root,  # type: str
    pex_hash,  # type: str
):
    # type: (...) -> str
    """Installs a zipapp or packed PEX into the pex root as a loose PEX.

    Returns the path of the installed PEX or `None` if the PEX needed no installation and can be
    executed directly.
    """
    with identify_layout(pex) as layout:
        return _ensure_installed(layout, pex_root, pex_hash)
