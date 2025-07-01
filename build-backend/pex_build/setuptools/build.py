# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import email
import functools
import hashlib
import os.path
import shutil
import subprocess
import sys
import tarfile
from collections import OrderedDict
from contextlib import closing, contextmanager
from zipfile import ZIP_DEFLATED

import pex_build
import setuptools.build_meta

# We re-export all setuptools' PEP-517 build backend hooks here for the build frontend to call.
from setuptools.build_meta import *  # NOQA

from pex import hashing, toml, windows
from pex.common import open_zip, safe_copy, safe_mkdir, safe_mkdtemp, temporary_dir
from pex.fs import lock
from pex.fs.lock import FileLockStyle
from pex.pep_376 import Hash, InstalledFile, Record
from pex.third_party.packaging.markers import Marker
from pex.typing import cast
from pex.version import __version__

if pex_build.TYPE_CHECKING:
    from typing import Any, Callable, Dict, Iterator, List, Optional


def get_requires_for_build_editable(config_settings=None):
    # type: (Optional[Dict[str, Any]]) -> List[str]

    # N.B.: The default setuptools implementation would eventually return nothing, but only after
    # running code that can temporarily pollute our project directory, foiling concurrent test runs;
    # so we short-circuit the answer here. Faster and safer.
    return []


def get_requires_for_build_sdist(config_settings=None):
    # type: (Optional[Dict[str, Any]]) -> List[str]

    # N.B.: The default setuptools implementation would eventually return nothing, but only after
    # running code that can temporarily pollute our project directory, foiling concurrent test runs;
    # so we short-circuit the answer here. Faster and safer.
    return []


@contextmanager
def _maybe_rewrite_project():
    # type: () -> Iterator[Optional[str]]

    if sys.version_info[:2] < (3, 9):
        yield None
        return

    # MyPy thinks this is unreachable when type checking for Python 3.8 or older.
    pyproject_toml = toml.load("pyproject.toml")  # type: ignore[unreachable]

    data = pyproject_toml
    for key in "tool.pex_build.setuptools.build.project".split("."):
        data = data.get(key, {})

    when = data.pop("when", None)
    if when and not Marker(when).evaluate():
        yield None
        return

    if not data:
        yield None
        return

    for key, value in data.items():
        pyproject_toml["project"][key] = value
    if when:
        data["when"] = when

    tmpdir = safe_mkdtemp()

    backup = os.path.join(tmpdir, "pyproject.toml.orig")
    shutil.copy("pyproject.toml", backup)

    modified = os.path.join(tmpdir, "pyproject.toml")
    with open(modified, "wb") as fp:
        toml.dump(pyproject_toml, fp)

    def preserve():
        preserved = os.path.join("dist", "pyproject.toml.modified")
        safe_mkdir("dist")
        shutil.copy(modified, preserved)
        print(
            "Preserved modified pyproject.toml at {preserved} for inspection.".format(
                preserved=preserved
            ),
            file=sys.stderr,
        )

    try:
        shutil.copy(modified, "pyproject.toml")
        yield backup
    except Exception:
        preserve()
        raise
    else:
        if os.environ.get("_PEX_BUILD_PRESERVE_PYPROJECT"):
            preserve()
    finally:
        shutil.move(backup, "pyproject.toml")


_PRESERVED_PYPROJECT_TOML = None  # type: Optional[str]


def _serialized_build(func):
    # type: (Callable) -> Callable

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        lck = lock.acquire(__file__ + ".lck", exclusive=True, style=FileLockStyle.BSD)
        try:
            with _maybe_rewrite_project() as preserved_pyproject_toml:
                global _PRESERVED_PYPROJECT_TOML
                _PRESERVED_PYPROJECT_TOML = preserved_pyproject_toml
                try:
                    return func(*args, **kwargs)
                finally:
                    _PRESERVED_PYPROJECT_TOML = None
        finally:
            lck.release()

    return wrapper


@_serialized_build
def build_sdist(
    sdist_directory,  # type: str
    config_settings=None,  # type: Optional[Dict[str, Any]]
):
    # type: (...) -> str

    for stub in windows.fetch_all_stubs():
        print("Embedded Windows script stub", stub.path, file=sys.stderr)

    tarball_name = cast(
        str, setuptools.build_meta.build_sdist(sdist_directory, config_settings=config_settings)
    )
    if _PRESERVED_PYPROJECT_TOML:
        tmpdir = safe_mkdtemp()
        tarball_root_dir_name = "pex-{version}".format(version=__version__)
        tarball_root_dir = os.path.join(tmpdir, tarball_root_dir_name)
        with closing(tarfile.open(os.path.join(sdist_directory, tarball_name))) as tf:
            tf.extractall(tmpdir)
            shutil.copy(_PRESERVED_PYPROJECT_TOML, os.path.join(tarball_root_dir, "pyproject.toml"))
        with closing(tarfile.open(os.path.join(sdist_directory, tarball_name), mode="w:gz")) as tf:
            tf.add(tarball_root_dir, tarball_root_dir_name)
    return tarball_name


def _maybe_rewrite_metadata(
    metadata_directory,  # type: str
    dist_info_dir,  # type: str
):
    # type: (...) -> str

    requires_python = os.environ.get("_PEX_REQUIRES_PYTHON")
    if requires_python:
        metadata_file = os.path.join(metadata_directory, dist_info_dir, "METADATA")
        with open(metadata_file) as fp:
            metadata = email.message_from_file(fp)
        del metadata["Requires-Python"]
        metadata["Requires-Python"] = requires_python
        with open(metadata_file, "w") as fp:
            fp.write(metadata.as_string())
    return dist_info_dir


@_serialized_build
def prepare_metadata_for_build_editable(
    metadata_directory,  # type: str
    config_settings=None,  # type: Optional[Dict[str, Any]]
):
    # type: (...) -> str

    return _maybe_rewrite_metadata(
        metadata_directory,
        setuptools.build_meta.prepare_metadata_for_build_editable(
            metadata_directory, config_settings=config_settings
        ),
    )


@_serialized_build
def get_requires_for_build_wheel(config_settings=None):
    # type: (Optional[Dict[str, Any]]) -> List[str]

    if not pex_build.INCLUDE_DOCS:
        return []

    pyproject_data = toml.load("pyproject.toml")
    return cast(
        "List[str]",
        # Here we skip any included dependency groups and just grab the direct doc requirements.
        [req for req in pyproject_data["dependency-groups"]["docs"] if isinstance(req, str)],
    )


@_serialized_build
def prepare_metadata_for_build_wheel(
    metadata_directory,  # type: str
    config_settings=None,  # type: Optional[Dict[str, Any]]
):
    # type: (...) -> str

    return _maybe_rewrite_metadata(
        metadata_directory,
        setuptools.build_meta.prepare_metadata_for_build_wheel(
            metadata_directory, config_settings=config_settings
        ),
    )


@_serialized_build
def build_wheel(
    wheel_directory,  # type: str
    config_settings=None,  # type: Optional[Dict[str, Any]]
    metadata_directory=None,  # type: Optional[str]
):
    # type: (...) -> str

    wheel = cast(
        str,
        setuptools.build_meta.build_wheel(
            wheel_directory, config_settings=config_settings, metadata_directory=metadata_directory
        ),
    )
    wheel_path = os.path.join(wheel_directory, wheel)
    with temporary_dir() as chroot:
        with open_zip(wheel_path) as zip_fp:
            zip_fp.extractall(chroot)

        dist_info_dir = "pex-{version}.dist-info".format(version=__version__)
        record_path = os.path.join(chroot, dist_info_dir, "RECORD")
        with open(record_path) as fp:
            installed_files_by_path = OrderedDict(
                (installed_file.path, installed_file) for installed_file in Record.read(fp)
            )

        for stub in windows.fetch_all_stubs():
            stub_relpath = os.path.relpath(
                stub.path, os.path.dirname(os.path.dirname(os.path.dirname(windows.__file__)))
            )
            if stub_relpath in installed_files_by_path:
                continue
            stub_dst = os.path.join(chroot, stub_relpath)
            safe_mkdir(os.path.dirname(stub_dst))
            safe_copy(stub.path, stub_dst)
            data = stub.read_data()
            installed_files_by_path[stub_relpath] = InstalledFile(
                path=stub_relpath,
                hash=Hash.create(hashlib.sha256(data)),
                size=len(data),
            )
            print("Embedded Windows script stub", stub.path, file=sys.stderr)

        if pex_build.INCLUDE_DOCS:
            out_dir = os.path.join(chroot, "pex", "docs")
            subprocess.check_call(
                args=[
                    sys.executable,
                    os.path.join("scripts", "build-docs.py"),
                    "--clean-html",
                    out_dir,
                ]
            )
            for root, _, files in os.walk(out_dir):
                for f in files:
                    src = os.path.join(root, f)
                    dst = os.path.relpath(src, chroot)
                    hasher = hashlib.sha256()
                    hashing.file_hash(src, digest=hasher)
                    installed_files_by_path[dst] = InstalledFile(
                        path=dst, hash=Hash.create(hasher), size=os.path.getsize(src)
                    )

        Record.write(record_path, installed_files_by_path.values())
        with open_zip(wheel_path, "w", compression=ZIP_DEFLATED) as zip_fp:

            def add_top_level_dir(name):
                # type: (str) -> None
                top = os.path.join(chroot, name)
                zip_fp.write(top, name + "/")
                for root, dirs, files in os.walk(top):
                    dirs[:] = sorted(dirs)
                    for path in sorted(files) + dirs:
                        src = os.path.join(root, path)
                        dst = os.path.relpath(src, chroot)
                        zip_fp.write(src, dst)

            add_top_level_dir("pex")
            add_top_level_dir(dist_info_dir)

    return wheel
