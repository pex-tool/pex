# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import hashlib
import os.path
import shutil
from contextlib import contextmanager
from textwrap import dedent

import pytest

from pex import resolver
from pex.common import open_zip, safe_copy, safe_mkdir, safe_open
from pex.http.server import Server
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import InterpreterConstraint
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pip.version import PipVersion
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.lockfile import json_codec
from pex.resolve.resolved_requirement import Pin
from pex.resolve.resolver_configuration import PipConfiguration, ResolverVersion
from pex.resolver import LocalDistribution
from pex.targets import LocalInterpreter, Targets
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper
from pex.wheel import Wheel
from testing import IS_MAC, PY311, ensure_python_interpreter
from testing.cli import run_pex3
from testing.pytest_utils import IS_CI
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Iterator

    import attr  # vendor:skip
else:
    from pex.third_party import attr


PROJECT_NAME = "p537"
VERSION = "1.0.8"
PRE_BUILT_WHEEL_REQUIRES = "CPython>=3.6,<3.15"


@pytest.fixture(scope="module")
def interpreter():
    # type: () -> PythonInterpreter

    current_interpreter = PythonInterpreter.get()
    if not InterpreterConstraint.matches(PRE_BUILT_WHEEL_REQUIRES, interpreter=current_interpreter):
        return PythonInterpreter.from_binary(ensure_python_interpreter(PY311))
    return current_interpreter


@pytest.fixture(scope="module")
def requirement(interpreter):
    # type: (PythonInterpreter) -> str

    return "{project_name}=={version}; sys_platform == '{sys_platform}'".format(
        project_name=PROJECT_NAME,
        version=VERSION,
        sys_platform=interpreter.identity.env_markers.sys_platform,
    )


@pytest.fixture(scope="module")
def downloaded_wheel(
    interpreter,  # type: PythonInterpreter
    requirement,  # type: str
):
    # type: (...) -> LocalDistribution

    target = LocalInterpreter.create(interpreter)
    pip_version = PipVersion.latest_compatible(target=target)

    downloaded = resolver.download(
        targets=Targets.from_target(target),
        requirements=[requirement],
        resolver=ConfiguredResolver(
            pip_configuration=PipConfiguration(
                version=pip_version, resolver_version=ResolverVersion.default(pip_version)
            )
        ),
    )
    assert 1 == len(downloaded.local_distributions)

    downloaded_wheel = downloaded.local_distributions[0]
    assert downloaded_wheel.is_wheel
    return downloaded_wheel


@attr.s(frozen=True)
class Index(object):
    url = attr.ib()  # type: str
    wheel_path = attr.ib()  # type: str


@contextmanager
def create_index(
    name,  # type: str
    tmpdir,  # type: Tempdir
    wheel,  # type: str
):
    # type: (...) -> Iterator[Index]

    project_name = ProjectName(PROJECT_NAME)
    document_root = tmpdir.join(name, "docroot")

    # N.B.: This format and layout matches the https://github.com/pex-tool/pex/issues/2631 indexes
    # in question:
    # + https://download.pytorch.org/whl/cpu/nvidia-cublas-cu12/
    # + https://download.pytorch.org/whl/cu129/nvidia-cublas-cu12/
    with safe_open(os.path.join(document_root, "index.html"), "w") as fp:
        fp.write(
            dedent(
                """\
                <!DOCTYPE html>
                <html>
                  <body>
                    <a href="{project_name}/">{project_name}</a>
                  </body>
                </html>
                """
            ).format(project_name=project_name.normalized)
        )

    project_dir = safe_mkdir(os.path.join(document_root, project_name.normalized))

    wheel_file = os.path.basename(wheel)
    wheel_path = os.path.join(project_dir, wheel_file)
    metadata_path = os.path.join(project_dir, "{wheel_file}.metadata".format(wheel_file=wheel_file))
    safe_copy(wheel, wheel_path)
    metadata_rel_path = Wheel.load(wheel_path).metadata_files.metadata.rel_path
    with open_zip(wheel_path, "a") as zip_fp:
        zip_fp.writestr(".different-contents", document_root.encode("utf-8"))
        with zip_fp.open(metadata_rel_path) as in_fp, safe_open(metadata_path, "wb") as out_fp:
            shutil.copyfileobj(in_fp, out_fp)

    with safe_open(os.path.join(project_dir, "index.html"), "w") as fp:
        fp.write(
            dedent(
                """\
                <!DOCTYPE html>
                <html>
                  <body>
                    <a href="/{project_name}/{wheel_file}"
                       data-dist-info-metadata="{metadata}"
                       data-core-metadata="{metadata}"
                    >
                      {wheel_file}
                    </a>
                  </body>
                </html>
                """
            ).format(
                project_name=project_name.normalized,
                wheel_file=wheel_file,
                metadata="sha256={hash}".format(
                    hash=CacheHelper.hash(metadata_path, hasher=hashlib.sha256)
                ),
            )
        )

    server = Server(name=name, cache_dir=tmpdir.join(name, "cache"))
    result = server.launch(
        document_root=document_root,
        timeout=float(os.environ.get("_PEX_HTTP_SERVER_TIMEOUT", "5.0")),
        verbose_error=True,
    )
    try:
        yield Index(url=result.server_info.url, wheel_path=wheel_path)
    finally:
        server.shutdown()


@pytest.fixture
def index1(
    tmpdir,  # type: Tempdir
    downloaded_wheel,  # type: LocalDistribution
):
    # type: (...) -> Iterator[Index]
    with create_index("index1", tmpdir, downloaded_wheel.path) as index:
        yield index


@pytest.fixture
def index2(
    tmpdir,  # type: Tempdir
    downloaded_wheel,  # type: LocalDistribution
):
    # type: (...) -> Iterator[Index]
    with create_index("index2", tmpdir, downloaded_wheel.path) as index:
        yield index


@pytest.mark.xfail(
    IS_CI and IS_MAC,
    reason=(
        "The index servers fail to start, at least on the macos-15 CI runners, and since this "
        "is not a multi-platform test (a universal lock can be created from any platform host), "
        "just checking on Linux is not ideal but good enough."
    ),
)
def test_multiple_wheels_with_same_name_and_different_hash(
    tmpdir,  # type: Tempdir
    interpreter,  # type: PythonInterpreter
    downloaded_wheel,  # type: LocalDistribution
    index1,  # type: Index
    index2,  # type: Index
    requirement,  # type: str
):
    # type: (...) -> None

    wheel1_hash = CacheHelper.hash(index1.wheel_path, hasher=hashlib.sha256)
    wheel2_hash = CacheHelper.hash(index2.wheel_path, hasher=hashlib.sha256)
    assert wheel1_hash != wheel2_hash

    pex_root = tmpdir.join("pex-root")
    lock_file = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--pip-version",
        "latest-compatible",
        "--resolver",
        "pip-2020-resolver",
        "--style",
        "universal",
        "--index",
        index1.url,
        "--index",
        index2.url,
        "--interpreter-constraint",
        "=={major}.{minor}.*".format(major=interpreter.version[0], minor=interpreter.version[1]),
        requirement,
        "--indent",
        "2",
        "-o",
        lock_file,
    ).assert_success()

    lock = json_codec.load(lock_file)
    assert 1 == len(lock.locked_resolves)

    locked_resolve = lock.locked_resolves[0]

    pin = Pin(project_name=ProjectName(PROJECT_NAME), version=Version(VERSION))
    locked_requirement = {
        locked_requirement.pin: locked_requirement
        for locked_requirement in locked_resolve.locked_requirements
    }.pop(pin)

    artifacts_by_hash = {
        artifact.fingerprint.hash: artifact for artifact in locked_requirement.iter_artifacts()
    }
    assert (
        len(artifacts_by_hash) >= 3
    ), "Expected at least 1 artifact from PyPI and 1 each for the find links repos."

    wheel1_artifact = artifacts_by_hash.pop(wheel1_hash)
    assert wheel1_artifact.url.normalized_url.startswith(index1.url)

    wheel2_artifact = artifacts_by_hash.pop(wheel2_hash)
    assert wheel2_artifact.url.normalized_url.startswith(index2.url)

    assert downloaded_wheel.fingerprint in artifacts_by_hash
    assert not any(
        artifact.url.normalized_url.startswith((index1.url, index2.url))
        for artifact in artifacts_by_hash.values()
    ), "Expected remaining artifacts to come from PyPI:\n{remaining_artifact_urls}".format(
        remaining_artifact_urls="\n".join(
            artifact.url.download_url for artifact in artifacts_by_hash.values()
        )
    )
