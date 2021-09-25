# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import zipfile
from abc import abstractmethod
from contextlib import contextmanager

from pex.common import atomic_directory, is_python_script, open_zip, safe_copy, safe_mkdir
from pex.enum import Enum
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.variables import unzip_dir

if TYPE_CHECKING:
    from typing import Optional, Iterator

BOOTSTRAP_DIR = ".bootstrap"
DEPS_DIR = ".deps"
PEX_INFO_PATH = "PEX-INFO"


class Layout(Enum["Layout.Value"]):
    class Value(Enum.Value):
        pass

    ZIPAPP = Value("zipapp")
    PACKED = Value("packed")
    LOOSE = Value("loose")


class _Layout(object):
    def __init__(self, path):
        # type: (str) -> None
        self._path = os.path.normpath(path)

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
    def extract_dist(
        self,
        dest_dir,  # type: str
        dist_relpath,  # type: str
    ):
        # type: (...) -> None
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


def _install(
    layout,  # type: _Layout
    pex_root,  # type: str
    pex_hash,  # type: str
):
    # type: (...) -> str
    with TRACER.timed("Laying out {}".format(layout)):
        pex = layout.path
        install_to = unzip_dir(pex_root=pex_root, pex_hash=pex_hash)
        with atomic_directory(install_to, exclusive=True) as chroot:
            if not chroot.is_finalized:
                with TRACER.timed("Installing {} to {}".format(pex, install_to)):
                    from pex.pex_info import PexInfo

                    pex_info = PexInfo.from_pex(pex)
                    pex_info.update(PexInfo.from_env())

                    bootstrap_cache = pex_info.bootstrap_cache
                    if bootstrap_cache is None:
                        raise AssertionError(
                            "Expected bootstrap_cache to be populated for {}.".format(layout)
                        )
                    code_hash = pex_info.code_hash
                    if code_hash is None:
                        raise AssertionError(
                            "Expected code_hash to be populated for {}.".format(layout)
                        )

                    with atomic_directory(
                        bootstrap_cache, source=layout.bootstrap_strip_prefix(), exclusive=True
                    ) as bootstrap_zip_chroot:
                        if not bootstrap_zip_chroot.is_finalized:
                            layout.extract_bootstrap(bootstrap_zip_chroot.work_dir)
                    os.symlink(
                        os.path.join(os.path.relpath(bootstrap_cache, install_to)),
                        os.path.join(chroot.work_dir, BOOTSTRAP_DIR),
                    )

                    for location, sha in pex_info.distributions.items():
                        spread_dest = os.path.join(pex_info.install_cache, sha, location)
                        dist_relpath = os.path.join(DEPS_DIR, location)
                        with atomic_directory(
                            spread_dest,
                            source=layout.dist_strip_prefix(location),
                            exclusive=True,
                        ) as spread_chroot:
                            if not spread_chroot.is_finalized:
                                layout.extract_dist(spread_chroot.work_dir, dist_relpath)
                        symlink_dest = os.path.join(chroot.work_dir, dist_relpath)
                        safe_mkdir(os.path.dirname(symlink_dest))
                        os.symlink(
                            os.path.relpath(
                                spread_dest,
                                os.path.join(install_to, os.path.dirname(dist_relpath)),
                            ),
                            symlink_dest,
                        )

                    code_dest = os.path.join(pex_info.zip_unsafe_cache, code_hash)
                    with atomic_directory(code_dest, exclusive=True) as code_chroot:
                        if not code_chroot.is_finalized:
                            layout.extract_code(code_chroot.work_dir)
                    for path in os.listdir(code_dest):
                        os.symlink(
                            os.path.join(os.path.relpath(code_dest, install_to), path),
                            os.path.join(chroot.work_dir, path),
                        )

                    layout.extract_pex_info(chroot.work_dir)
                    layout.extract_main(chroot.work_dir)

        return install_to


class _ZipAppPEX(_Layout):
    def __init__(
        self,
        path,  # type: str
        zfp,  # type: zipfile.ZipFile
    ):
        # type: (...) -> None
        super(_ZipAppPEX, self).__init__(path)
        self._zfp = zfp
        self._names = tuple(zfp.namelist())

    def bootstrap_strip_prefix(self):
        # type: () -> Optional[str]
        return BOOTSTRAP_DIR

    def extract_bootstrap(self, dest_dir):
        # type: (str) -> None
        for name in self._names:
            if name.startswith(BOOTSTRAP_DIR) and not name.endswith("/"):
                self._zfp.extract(name, dest_dir)

    def dist_strip_prefix(self, dist_name):
        # type: (str) -> Optional[str]
        return os.path.join(DEPS_DIR, dist_name)

    def extract_dist(
        self,
        dest_dir,  # type: str
        dist_relpath,  # type: str
    ):
        for name in self._names:
            if name.startswith(dist_relpath) and not name.endswith("/"):
                self._zfp.extract(name, dest_dir)

    def extract_code(self, dest_dir):
        # type: (str) -> None
        for name in self._names:
            if name not in ("__main__.py", PEX_INFO_PATH) and not name.startswith(
                (BOOTSTRAP_DIR, DEPS_DIR)
            ):
                self._zfp.extract(name, dest_dir)

    def extract_pex_info(self, dest_dir):
        # type: (str) -> None
        self._zfp.extract(PEX_INFO_PATH, dest_dir)

    def extract_main(self, dest_dir):
        # type: (str) -> None
        self._zfp.extract("__main__.py", dest_dir)

    def __str__(self):
        return "PEX zipfile {}".format(self._path)


class _PackedPEX(_Layout):
    def extract_bootstrap(self, dest_dir):
        # type: (str) -> None
        with open_zip(os.path.join(self._path, BOOTSTRAP_DIR)) as zfp:
            zfp.extractall(dest_dir)

    def extract_dist(
        self,
        dest_dir,  # type: str
        dist_relpath,  # type: str
    ):
        with open_zip(os.path.join(self._path, dist_relpath)) as zfp:
            zfp.extractall(dest_dir)

    def extract_code(self, dest_dir):
        # type: (str) -> None
        for root, dirs, files in os.walk(self._path):
            rel_root = os.path.relpath(root, self._path)
            if root == self._path:
                dirs[:] = [d for d in dirs if d != DEPS_DIR]
                files[:] = [
                    f for f in files if f not in ("__main__.py", PEX_INFO_PATH, BOOTSTRAP_DIR)
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

    def __str__(self):
        return "Spread PEX directory {}".format(self._path)


@contextmanager
def _identify_layout(pex):
    # type: (str) -> Iterator[Optional[_Layout]]
    if zipfile.is_zipfile(pex) and is_python_script(
        pex,
        # N.B.: A PEX file need not be executable since it can always be run via `python a.pex`.
        check_executable=False,
    ):
        with open_zip(pex) as zfp:
            yield _ZipAppPEX(pex, zfp)
    elif os.path.isdir(pex) and zipfile.is_zipfile(os.path.join(pex, BOOTSTRAP_DIR)):
        yield _PackedPEX(pex)
    else:
        # A loose PEX which needs no layout.
        yield None


def maybe_install(
    pex,  # type: str
    pex_root,  # type: str
    pex_hash,  # type: str
):
    # type: (...) -> Optional[str]
    """Installs a zipapp or packed PEX into the pex root as a loose PEX.

    Returns the path of the installed PEX or `None` if the PEX needed no installation and can be
    executed directly.
    """
    with _identify_layout(pex) as layout:
        if layout:
            return _install(layout, pex_root, pex_hash)
    return None
