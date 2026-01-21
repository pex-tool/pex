# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import base64
import csv
import glob
import hashlib
import io
import os
import tarfile

from pex import sdist
from pex.build_backend import BuildError
from pex.build_backend.configuration import load_config
from pex.build_backend.pylock import ScriptLocks
from pex.common import (
    DETERMINISTIC_DATETIME,
    DETERMINISTIC_DATETIME_TIMESTAMP,
    ZipFileEx,
    deterministic_walk,
    open_zip,
    safe_mkdtemp,
)
from pex.compatibility import PY2
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Callable, Dict, Iterator, Optional, Sequence, Tuple


_CONFIG = load_config(internal_plugins=[(ScriptLocks.CONFIG_KEY, ScriptLocks)])
_CONFIG.export_build_backend_hooks(namespace=globals())


def _build_dir(name):
    # type: (str) -> str
    return safe_mkdtemp(prefix="pex.build_backend.", suffix=".{name}-build-dir".format(name=name))


def _iter_files_deterministic(directory):
    # type: (str) -> Iterator[str]
    for root, _, files in deterministic_walk(directory):
        for path in files:
            yield os.path.relpath(os.path.join(root, path), directory)


def build_sdist(
    sdist_directory,  # type: str
    config_settings=None,  # type: Optional[Dict[str, Any]]
):
    # type: (...) -> str

    sdist_name = cast(
        str,
        _CONFIG.build_backend.build_sdist(  # type: ignore[attr-defined]
            sdist_directory, config_settings
        ),
    )
    plugins = tuple(plugin for plugin in _CONFIG.plugins if plugin.modifies_sdists)
    if not plugins:
        return sdist_name

    sdist_path = os.path.join(sdist_directory, sdist_name)
    build_dir = _build_dir("sdist")
    tarball_root_dir = sdist.extract_tarball(sdist_path, dest_dir=build_dir)
    for plugin in plugins:
        plugin.modify_sdist(tarball_root_dir)

    with tarfile.open(sdist_path, "w:gz") as tf:
        for path in _iter_files_deterministic(build_dir):
            abs_path = os.path.join(build_dir, path)
            tar_info = tf.gettarinfo(name=abs_path, arcname=path)
            if _CONFIG.deterministic:
                tar_info.mtime = DETERMINISTIC_DATETIME_TIMESTAMP
            with open(abs_path, "rb") as fp:
                tf.addfile(tar_info, fp)

    return sdist_name


if TYPE_CHECKING:
    from typing import Protocol

    class CSVWriter(Protocol):
        def writerow(self, row):
            # type: (Sequence[Any]) -> None
            pass


def csv_output():
    # type: () -> Tuple[CSVWriter, Callable[[], bytes]]
    if PY2:
        record = io.BytesIO()
        csv_writer = csv.writer(record, delimiter=",", quotechar='"', lineterminator="\n")
        return csv_writer, record.getvalue
    else:
        record = io.StringIO()
        csv_writer = csv.writer(record, delimiter=",", quotechar='"', lineterminator="\n")
        return csv_writer, lambda: record.getvalue().encode("utf-8")


def build_wheel(
    wheel_directory,  # type: str
    config_settings=None,  # type: Optional[Dict[str, Any]]
    metadata_directory=None,  # type: Optional[str]
):
    # type: (...) -> str

    wheel_name = cast(
        str,
        _CONFIG.build_backend.build_wheel(  # type: ignore[attr-defined]
            wheel_directory, config_settings, metadata_directory
        ),
    )

    plugins = tuple(plugin for plugin in _CONFIG.plugins if plugin.modifies_wheels)
    if not plugins:
        return wheel_name

    wheel_path = os.path.join(wheel_directory, wheel_name)
    build_dir = _build_dir("wheel")

    with open_zip(wheel_path) as zf:
        zf.extractall(build_dir)

    entries = glob.glob(os.path.join(build_dir, "*.dist-info"))
    if len(entries) != 1:
        raise BuildError(
            "Calling `{backend}.build_wheel` produced an wheel with unexpected contents.\n"
            "Expected expected one top-level <project>-<version>.dist-info directory but found "
            "{count}:\n"
            "{entries}".format(
                backend=_CONFIG.delegate_build_backend,
                count=len(entries),
                entries="\n".join(entries),
            )
        )

    dist_info_dir_relpath = os.path.relpath(entries[0], build_dir)
    for plugin in plugins:
        plugin.modify_wheel(wheel_dir=build_dir, dist_info_dir_relpath=dist_info_dir_relpath)

    date_time = DETERMINISTIC_DATETIME.timetuple() if _CONFIG.deterministic else None
    record_relpath = os.path.join(dist_info_dir_relpath, "RECORD")
    record_zinfo, _ = ZipFileEx.zip_info_from_file(
        os.path.join(build_dir, record_relpath), arcname=record_relpath, date_time=date_time
    )
    csv_writer, get_csv_bytes = csv_output()
    with open_zip(wheel_path, "w") as zf:
        for path in _iter_files_deterministic(build_dir):
            if path == record_relpath:
                continue

            digest = hashlib.sha256()
            size = zf.write_deterministic(
                os.path.join(build_dir, path),
                arcname=path,
                digest=digest,
                deterministic=_CONFIG.deterministic,
            )
            fingerprint = base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode("ascii")
            csv_writer.writerow(
                (path, "sha256={fingerprint}".format(fingerprint=fingerprint), size)
            )

        csv_writer.writerow((record_relpath, None, None))
        zf.writestr(record_zinfo, get_csv_bytes())

    return wheel_name
