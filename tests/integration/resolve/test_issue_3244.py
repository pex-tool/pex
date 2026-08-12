# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import os.path
import subprocess
import sys

import pytest

from pex import hashing
from pex.enum import Enum
from pex.layout import Layout
from pex.pep_427 import InstallableType
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from testing import run_command_with_jitter, run_pex_command
from testing.cli import run_pex3
from testing.pep_427 import get_installable_type_flag
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Callable, List


REQUIREMENTS = ["cowsay<6"]


def generate_pex_repository_args(tmpdir):
    # type: (Tempdir) -> List[str]
    pex = tmpdir.join("repository.pex")
    run_pex_command(args=["-o", pex] + REQUIREMENTS).assert_success()
    return ["--pex-repository", pex]


def generate_lock(tmpdir):
    # type: (Tempdir) -> str
    lock = tmpdir.join("lock.json")
    run_pex3("lock", "create", "-o", lock, "--indent", "2", *REQUIREMENTS).assert_success()
    return lock


def generate_lock_args(tmpdir):
    # type: (Tempdir) -> List[str]
    return ["--lock", generate_lock(tmpdir)]


def generate_pre_resolved_args(tmpdir):
    # type: (Tempdir) -> List[str]
    wheels = tmpdir.join("wheels")
    run_pex3("wheel", "-d", wheels, *REQUIREMENTS).assert_success()
    return ["--pre-resolved-dists", wheels]


def generate_pylock_args(tmpdir):
    # type: (Tempdir) -> List[str]
    pylock = tmpdir.join("pylock.toml")
    run_pex3("lock", "export", "--format", "pep-751", "-o", pylock, generate_lock(tmpdir))
    return ["--pylock", pylock]


def generate_venv_args(tmpdir):
    # type: (Tempdir) -> List[str]

    if sys.version_info < (3, 8):
        pytest.skip(
            "This test uses uv to generate venvs, but uv does not support Python {version}".format(
                version=sys.version
            )
        )

    venv_dir = tmpdir.join("venv")
    venv = Virtualenv.create(venv_dir)
    subprocess.check_call(
        args=["uv", "pip", "install", "--python", venv.interpreter.binary] + REQUIREMENTS
    )
    subprocess.check_call(
        args=["uv", "pip", "install", "--python", venv.interpreter.binary] + REQUIREMENTS
    )
    return ["--venv-repository", venv_dir]


class RepositoryValue(Enum.Value):
    def __init__(
        self,
        value,  # type: str
        generate_func,  # type: Callable[[Tempdir], List[str]]
    ):  # type: (...) -> None
        super(RepositoryValue, self).__init__(value)
        self._generate_func = generate_func

    def generate_args(self, tmpdir):
        # type: (Tempdir) -> List[str]
        return self._generate_func(tmpdir)


class Repository(Enum["Repository.Value"]):
    class Value(RepositoryValue):
        pass

    PIP = Value("pip", lambda _: [])
    PEX = Value("pex", generate_pex_repository_args)
    LOCK = Value("lock", generate_lock_args)
    PRE_RESOLVED = Value("pre-resolved", generate_pre_resolved_args)
    PYLOCK = Value("pylock", generate_pylock_args)
    VENV = Value("venv", generate_venv_args)


Repository.seal()


def generate_repository_args(
    repository_type,  # type: Repository.Value
    tmpdir,  # type: Tempdir
):
    # type: (...) -> List[str]
    pass


@pytest.mark.parametrize(
    "repository_type",
    [pytest.param(repository, id=repository.value) for repository in Repository.values()],
)
@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
@pytest.mark.parametrize(
    "installable_type",
    [
        pytest.param(installable_type, id=installable_type.value)
        for installable_type in InstallableType.values()
    ],
)
def test_reproducible_pex(
    tmpdir,  # type: Tempdir
    repository_type,  # type: Repository.Value
    layout,  # type: Layout.Value
    installable_type,  # type: InstallableType.Value
):
    # type: (...) -> None

    pex1, pex2 = run_command_with_jitter(
        args=[
            sys.executable,
            "-m",
            "pex",
            "--layout",
            layout.value,
            get_installable_type_flag(installable_type),
        ]
        + repository_type.generate_args(tmpdir)
        + REQUIREMENTS,
        path_argument="-o",
        count=2,
        dest=tmpdir.join("jitter-chroot"),
    )

    def fingerprint(pex):
        # type: (str) -> str
        digest = hashlib.sha256()
        if os.path.isfile(pex):
            hashing.file_hash(path=pex, digest=digest)
        else:
            hashing.dir_hash(directory=pex, digest=digest)
        return digest.hexdigest()

    assert fingerprint(pex1) == fingerprint(pex2)
