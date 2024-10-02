# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import os.path
import sqlite3
from collections import OrderedDict
from contextlib import closing, contextmanager

from pex.atomic_directory import atomic_directory
from pex.cache.dirs import (
    BootstrapDir,
    CacheDir,
    InstalledWheelDir,
    UnzipDir,
    UserCodeDir,
    VenvDirs,
)
from pex.dist_metadata import ProjectNameAndVersion
from pex.typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from typing import (
        Callable,
        Dict,
        Iterable,
        Iterator,
        List,
        Optional,
        Sequence,
        Tuple,
        TypeVar,
        Union,
    )

    from pex.pex_info import PexInfo


_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE wheels (
    name TEXT NOT NULL,
    install_hash TEXT NOT NULL,
    wheel_hash TEXT,
    project_name TEXT NOT NULL,
    version TEXT NOT NULL,
    PRIMARY KEY (name ASC, install_hash ASC)
) WITHOUT ROWID;
CREATE UNIQUE INDEX wheels_idx_install_hash ON wheels (install_hash ASC);
CREATE INDEX wheels_idx_project_name_version ON wheels (project_name ASC, version ASC);

CREATE TABLE zipapps (
    pex_hash TEXT PRIMARY KEY ASC,
    bootstrap_hash TEXT NOT NULL,
    code_hash TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX zipapps_idx_bootstrap_hash ON zipapps (bootstrap_hash ASC);
CREATE INDEX zipapps_idx_code_hash ON zipapps (code_hash ASC);

CREATE TABLE zipapp_deps (
    pex_hash TEXT NOT NULL REFERENCES zipapps(pex_hash) ON DELETE CASCADE,
    wheel_install_hash TEXT NOT NULL REFERENCES wheels(install_hash) ON DELETE CASCADE
);
CREATE INDEX zipapp_deps_idx_pex_hash ON zipapp_deps (pex_hash ASC);
CREATE INDEX zipapp_deps_idx_wheel_install_hash ON zipapp_deps (wheel_install_hash ASC);

CREATE TABLE venv_deps (
    venv_hash TEXT NOT NULL,
    wheel_install_hash TEXT NOT NULL REFERENCES wheels(install_hash) ON DELETE CASCADE
);
CREATE INDEX venv_deps_idx_venv_hash ON venv_deps (venv_hash ASC);
CREATE INDEX venv_deps_idx_wheel_hash ON venv_deps (wheel_install_hash ASC);
"""


@contextmanager
def _db_connection(conn=None):
    # type: (Optional[sqlite3.Connection]) -> Iterator[sqlite3.Connection]
    if conn:
        yield conn
    else:
        db_dir = CacheDir.DBS.path("deps")
        with atomic_directory(db_dir) as atomic_dir:
            if not atomic_dir.is_finalized():
                with sqlite3.connect(os.path.join(atomic_dir.work_dir, "deps.db")) as conn:
                    conn.executescript(_SCHEMA).close()
        with sqlite3.connect(os.path.join(db_dir, "deps.db")) as conn:
            conn.executescript(
                """
                PRAGMA synchronous=NORMAL;
                PRAGMA foreign_keys=ON;
                """
            ).close()
            yield conn


@contextmanager
def _inserted_wheels(pex_info):
    # type: (PexInfo) -> Iterator[sqlite3.Cursor]

    wheels = []  # type: List[Dict[str, Optional[str]]]
    for wheel_name, install_hash in pex_info.distributions.items():
        installed_wheel_dir = InstalledWheelDir.create(wheel_name, install_hash)
        pnav = ProjectNameAndVersion.from_filename(wheel_name)
        wheels.append(
            dict(
                name=wheel_name,
                install_hash=install_hash,
                wheel_hash=installed_wheel_dir.wheel_hash,
                project_name=str(pnav.canonicalized_project_name),
                version=str(pnav.canonicalized_version),
            )
        )

    with _db_connection() as conn:
        cursor = conn.executemany(
            """
            INSERT INTO wheels (
                name,
                install_hash,
                wheel_hash,
                project_name,
                version
            ) VALUES (:name, :install_hash, :wheel_hash, :project_name, :version)
            ON CONFLICT (name, install_hash) DO UPDATE SET wheel_hash = :wheel_hash
            """,
            wheels,
        )
        yield cursor
        cursor.close()


def record_zipapp_install(pex_info):
    # type: (PexInfo) -> None

    with _inserted_wheels(pex_info) as cursor:
        cursor.execute(
            """
            INSERT OR IGNORE INTO zipapps (
                pex_hash,
                bootstrap_hash,
                code_hash
            ) VALUES (?, ?, ?)
            """,
            (pex_info.pex_hash, pex_info.bootstrap_hash, pex_info.code_hash),
        ).executemany(
            """
            INSERT OR IGNORE INTO zipapp_deps (
                pex_hash,
                wheel_install_hash
            ) VALUES (?, ?)
            """,
            tuple(
                (pex_info.pex_hash, wheel_install_hash)
                for wheel_install_hash in pex_info.distributions.values()
            ),
        ).close()


def record_venv_install(
    pex_info,  # type: PexInfo
    venv_dirs,  # type: VenvDirs
):
    # type: (...) -> None

    with _inserted_wheels(pex_info) as cursor:
        cursor.executemany(
            """
            INSERT OR IGNORE INTO venv_deps (
                venv_hash,
                wheel_install_hash
            ) VALUES (?, ?)
            """,
            tuple(
                (venv_dirs.short_hash, wheel_install_hash)
                for wheel_install_hash in pex_info.distributions.values()
            ),
        ).close()


if TYPE_CHECKING:
    _I = TypeVar("_I")
    _K = TypeVar("_K")


@overload
def _iter_key_chunks(items):
    # type: (Sequence[_K]) -> Iterator[Tuple[str, Sequence[_K]]]
    pass


@overload
def _iter_key_chunks(
    items,  # type: Sequence[_I]
    extract_key,  # type: Callable[[_I], _K]
):
    # type: (...) -> Iterator[Tuple[str, Sequence[_K]]]
    pass


def _iter_key_chunks(
    items,  # type: Sequence
    extract_key=None,  # type: Optional[Callable[[_I], _K]]
):
    # type: (...) -> Iterator[Tuple[str, Sequence[_K]]]

    # N.B.: Maximum parameter count is 999 in pre-2020 versions of SQLite 3; so we limit
    # to an even lower chunk size to be safe: https://www.sqlite.org/limits.html
    chunk_size = 100
    for index in range(0, len(items), chunk_size):
        item_chunk = items[index : index + chunk_size]
        keys = tuple(map(extract_key, item_chunk) if extract_key else item_chunk)
        placeholders = ", ".join(itertools.repeat("?", len(keys)))
        yield placeholders, keys


def _zipapp_deps(
    unzip_dirs,  # type: Sequence[UnzipDir]
    connection=None,  # type: Optional[sqlite3.Connection]
):
    # type: (...) -> Iterator[Union[BootstrapDir, UserCodeDir, InstalledWheelDir]]

    with _db_connection(conn=connection) as conn:
        for placeholders, keys in _iter_key_chunks(unzip_dirs, extract_key=lambda u: u.pex_hash):
            with closing(
                conn.execute(
                    """
                    SELECT bootstrap_hash, code_hash FROM zipapps WHERE pex_hash IN ({keys})
                    """.format(
                        keys=placeholders
                    ),
                    keys,
                )
            ) as cursor:
                for bootstrap_hash, code_hash in cursor:
                    yield BootstrapDir.create(bootstrap_hash)
                    yield UserCodeDir.create(code_hash)

            with closing(
                conn.execute(
                    """
                    SELECT name, install_hash, wheel_hash FROM wheels
                    JOIN zipapp_deps ON zipapp_deps.wheel_install_hash = wheels.install_hash
                    WHERE zipapp_deps.pex_hash in ({keys})
                    """.format(
                        keys=placeholders
                    ),
                    keys,
                )
            ) as cursor:
                for name, install_hash, wheel_hash in cursor:
                    yield InstalledWheelDir.create(
                        wheel_name=name, install_hash=install_hash, wheel_hash=wheel_hash
                    )


def _venv_deps(
    venv_dirs,  # type: Sequence[VenvDirs]
    connection=None,  # type: Optional[sqlite3.Connection]
):
    # type: (...) -> Iterator[InstalledWheelDir]

    with _db_connection(conn=connection) as conn:
        for placeholders, keys in _iter_key_chunks(venv_dirs, extract_key=lambda v: v.short_hash):
            with closing(
                conn.execute(
                    """
                    SELECT name, install_hash, wheel_hash FROM wheels
                    JOIN venv_deps ON venv_deps.wheel_install_hash = wheels.install_hash
                    WHERE venv_deps.venv_hash IN ({keys})
                    """.format(
                        keys=placeholders
                    ),
                    keys,
                )
            ) as cursor:
                for name, install_hash, wheel_hash in cursor:
                    yield InstalledWheelDir.create(
                        wheel_name=name, install_hash=install_hash, wheel_hash=wheel_hash
                    )


def dir_dependencies(
    pex_dirs,  # type: Iterable[Union[UnzipDir, VenvDirs]]
    connection=None,  # type: Optional[sqlite3.Connection]
):
    # type: (...) -> Iterator[Union[BootstrapDir, UserCodeDir, InstalledWheelDir]]

    seen = set()
    with _db_connection(conn=connection) as conn:
        for dep in _zipapp_deps(
            [pex_dir for pex_dir in pex_dirs if isinstance(pex_dir, UnzipDir)], connection=conn
        ):
            if dep not in seen:
                seen.add(dep)
                yield dep

        for dep in _venv_deps(
            [venv_dirs for venv_dirs in pex_dirs if isinstance(venv_dirs, VenvDirs)],
            connection=conn,
        ):
            if dep not in seen:
                seen.add(dep)
                yield dep


@contextmanager
def delete(
    pex_dirs,  # type: Iterable[Union[UnzipDir, VenvDirs]]
    dry_run=False,  # type: bool
):
    # type: (...) -> Iterator[Iterator[Union[BootstrapDir, UserCodeDir, InstalledWheelDir]]]

    with _db_connection() as conn:
        yield dir_dependencies(pex_dirs, connection=conn)

        if not dry_run:
            for placeholders, keys in _iter_key_chunks(
                [pex_dir for pex_dir in pex_dirs if isinstance(pex_dir, UnzipDir)],
                extract_key=lambda u: u.pex_hash,
            ):
                conn.execute(
                    "DELETE FROM zipapps WHERE pex_hash IN ({keys})".format(keys=placeholders), keys
                ).close()


@contextmanager
def prune(
    deps,  # type: Iterable[Union[BootstrapDir, UserCodeDir, InstalledWheelDir]]
):
    # type: (...) -> Iterator[Iterator[Union[BootstrapDir, UserCodeDir, InstalledWheelDir]]]

    with _db_connection() as conn:
        bootstraps_by_hash = OrderedDict(
            (dep.bootstrap_hash, dep) for dep in deps if isinstance(dep, BootstrapDir)
        )  # type: OrderedDict[str, BootstrapDir]
        for placeholders, keys in _iter_key_chunks(tuple(bootstraps_by_hash.keys())):
            with closing(
                conn.execute(
                    """
                    SELECT bootstrap_hash FROM zipapps WHERE bootstrap_hash IN ({keys})
                    """.format(
                        keys=placeholders
                    ),
                    keys,
                )
            ) as cursor:
                for [bootstrap_hash] in cursor:
                    bootstraps_by_hash.pop(bootstrap_hash)

        user_code_by_hash = OrderedDict(
            (dep.code_hash, dep) for dep in deps if isinstance(dep, UserCodeDir)
        )  # type: OrderedDict[str, UserCodeDir]
        for placeholders, keys in _iter_key_chunks(tuple(user_code_by_hash.keys())):
            with closing(
                conn.execute(
                    """
                    SELECT code_hash FROM zipapps WHERE code_hash IN ({keys})
                    """.format(
                        keys=placeholders
                    ),
                    keys,
                )
            ) as cursor:
                for [code_hash] in cursor:
                    user_code_by_hash.pop(code_hash)

        wheels_by_hash = OrderedDict(
            (dep.install_hash, dep) for dep in deps if isinstance(dep, InstalledWheelDir)
        )  # type: OrderedDict[str, InstalledWheelDir]
        for placeholders, keys in _iter_key_chunks(tuple(wheels_by_hash.keys())):
            with closing(
                conn.execute(
                    """
                    SELECT DISTINCT wheels.install_hash
                    FROM wheels
                    LEFT JOIN zipapp_deps ON zipapp_deps.wheel_install_hash = wheels.install_hash
                    LEFT JOIN venv_deps ON venv_deps.wheel_install_hash = wheels.install_hash
                    WHERE wheels.install_hash IN ({keys}) AND (
                        zipapp_deps.pex_hash IS NOT NULL OR venv_deps.venv_hash IS NOT NULL
                    )
                    """.format(
                        keys=placeholders
                    ),
                    keys,
                )
            ) as cursor:
                for [install_hash] in cursor:
                    wheels_by_hash.pop(install_hash)

        yield itertools.chain(
            bootstraps_by_hash.values(), user_code_by_hash.values(), wheels_by_hash.values()
        )

        for placeholders, keys in _iter_key_chunks(tuple(wheels_by_hash.keys())):
            conn.execute(
                "DELETE FROM wheels WHERE install_hash in ({keys})".format(keys=placeholders), keys
            ).close()
