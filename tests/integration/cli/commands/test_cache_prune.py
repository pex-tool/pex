# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_nothing_prunable(tmpdir):
    # type: (Any) -> None
    pass


def test_installed_wheel_prune_build_time(tmpdir):
    # type: (Any) -> None
    pass


def test_installed_wheel_prune_run_time(tmpdir):
    # type: (Any) -> None
    pass


def test_zipapp_prune(tmpdir):
    # type: (Any) -> None
    pass


def test_zipapp_prune_shared_bootstrap(tmpdir):
    # type: (Any) -> None
    pass


def test_zipapp_prune_shared_code(tmpdir):
    # type: (Any) -> None
    pass


def test_zipapp_prune_shared_deps(tmpdir):
    # type: (Any) -> None
    pass


def test_venv_prune_symlinks(tmpdir):
    # type: (Any) -> None
    pass


def test_venv_prune_no_symlinks(tmpdir):
    # type: (Any) -> None
    pass
