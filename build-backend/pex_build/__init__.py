# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import functools
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager

from pex import hashing, toml, windows
from pex.common import safe_mkdir, safe_mkdtemp
from pex.third_party.packaging.markers import Marker
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable, Iterator, Optional

INCLUDE_DOCS = os.environ.get("__PEX_BUILD_INCLUDE_DOCS__", "False").lower() in ("1", "true")


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


def serialized_build(func):
    # type: (Callable) -> Callable

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with hashing.lock_pex_project_dir():
            with _maybe_rewrite_project() as preserved_pyproject_toml:
                global _PRESERVED_PYPROJECT_TOML
                _PRESERVED_PYPROJECT_TOML = preserved_pyproject_toml
                try:
                    return func(*args, **kwargs)
                finally:
                    _PRESERVED_PYPROJECT_TOML = None

    return wrapper


def modify_sdist(sdist_dir):
    # type: (str) -> None
    for stub in windows.fetch_all_stubs(sdist_dir):
        print("Embedded Windows script stub", stub.path, file=sys.stderr)
    if _PRESERVED_PYPROJECT_TOML:
        shutil.copy(_PRESERVED_PYPROJECT_TOML, os.path.join(sdist_dir, "pyproject.toml"))


def modify_wheel(
    wheel_dir,  # type: str
    dist_info_dir_relpath,  # type: str
):
    # type: (...) -> None
    for stub in windows.fetch_all_stubs(wheel_dir):
        print("Embedded Windows script stub", stub.path, file=sys.stderr)
    if INCLUDE_DOCS:
        out_dir = os.path.join(wheel_dir, "pex", "docs")
        subprocess.check_call(
            args=[
                sys.executable,
                os.path.join("scripts", "build-docs.py"),
                "--clean-html",
                out_dir,
            ]
        )
