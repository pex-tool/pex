# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import os
import warnings

import pytest

from pex import targets
from pex.common import safe_rmtree
from pex.interpreter import PythonInterpreter
from pex.jobs import Job
from pex.pip.tool import PackageIndexConfiguration, Pip
from pex.platforms import Platform
from pex.targets import AbbreviatedPlatform, LocalInterpreter, Target
from pex.testing import PY310, ensure_python_interpreter, environment_as
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import Any, Iterator, Optional, Protocol

    class CreatePip(Protocol):
        def __call__(
            self,
            interpreter,  # type: Optional[PythonInterpreter]
            **extra_env  # type: str
        ):
            # type: (...) -> Pip
            pass


@pytest.fixture
def current_interpreter():
    # type: () -> PythonInterpreter
    return PythonInterpreter.get()


@pytest.fixture
def pex_root(tmpdir):
    # type: (Any) -> str
    return os.path.join(str(tmpdir), "pex_root")


@pytest.fixture
def create_pip(
    pex_root,  # type: str
    tmpdir,  # type: Any
):
    # type: (...) -> Iterator[CreatePip]
    pex_root = os.path.join(str(tmpdir), "pex_root")
    pip_root = os.path.join(str(tmpdir), "pip_root")

    def create_pip(
        interpreter,  # type: Optional[PythonInterpreter]
        **extra_env  # type: str
    ):
        # type: (...) -> Pip
        with ENV.patch(PEX_ROOT=pex_root, **extra_env):
            return Pip.create(path=pip_root, interpreter=interpreter)

    yield create_pip


def test_no_duplicate_constraints_pex_warnings(
    create_pip,  # type: CreatePip
    current_interpreter,  # type: PythonInterpreter
):
    # type: (...) -> None
    with warnings.catch_warnings(record=True) as events:
        pip = create_pip(current_interpreter)

    platform = current_interpreter.platform
    pip.spawn_debug(
        platform=platform.platform, impl=platform.impl, version=platform.version, abi=platform.abi
    ).wait()

    assert 0 == len([event for event in events if "constraints.txt" in str(event)]), (
        "Expected no duplicate constraints warnings to be emitted when creating a Pip venv but "
        "found\n{}".format("\n".join(map(str, events)))
    )


def test_download_platform_issues_1355(
    create_pip,  # type: CreatePip
    current_interpreter,  # type: PythonInterpreter
    tmpdir,  # type: Any
):
    # type: (...) -> None
    pip = create_pip(current_interpreter)
    download_dir = os.path.join(str(tmpdir), "downloads")

    def download_ansicolors(
        target=None,  # type: Optional[Target]
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
    ):
        # type: (...) -> Job
        safe_rmtree(download_dir)
        return pip.spawn_download_distributions(
            download_dir=download_dir,
            requirements=["ansicolors==1.0.2"],
            transitive=False,
            target=target,
            package_index_configuration=package_index_configuration,
        )

    def assert_ansicolors_downloaded(target=None):
        # type: (Optional[Target]) -> None
        download_ansicolors(target=target).wait()
        assert ["ansicolors-1.0.2.tar.gz"] == os.listdir(download_dir)

    # The only ansicolors 1.0.2 dist on PyPI is an sdist and we should be able to download one of
    # those with the current interpreter since we have an interpreter in hand to build a wheel from
    # it with later.
    assert_ansicolors_downloaded()
    assert_ansicolors_downloaded(target=targets.current())
    assert_ansicolors_downloaded(target=LocalInterpreter.create(current_interpreter))

    wheel_dir = os.path.join(str(tmpdir), "wheels")
    pip.spawn_build_wheels(
        distributions=glob.glob(os.path.join(download_dir, "*.tar.gz")),
        wheel_dir=wheel_dir,
        interpreter=current_interpreter,
    ).wait()
    built_wheels = glob.glob(os.path.join(wheel_dir, "*.whl"))
    assert len(built_wheels) == 1

    ansicolors_wheel = built_wheels[0]
    local_wheel_repo = PackageIndexConfiguration.create(find_links=[wheel_dir])
    current_platform = AbbreviatedPlatform.create(current_interpreter.platform)

    # We should fail to find a wheel for ansicolors 1.0.2 and thus fail to download for a target
    # Platform, even if that target platform happens to match the current interpreter we're
    # executing Pip with.
    with pytest.raises(Job.Error):
        download_ansicolors(target=current_platform).wait()

    # If we point the target Platform to a find-links repo with the wheel just-built though, the
    # download should proceed without error.
    download_ansicolors(
        target=current_platform, package_index_configuration=local_wheel_repo
    ).wait()
    assert [os.path.basename(ansicolors_wheel)] == os.listdir(download_dir)


def assert_download_platform_markers_issue_1366(
    create_pip,  # type: CreatePip
    tmpdir,  # type: Any
):
    # type: (...) -> None
    python310_interpreter = PythonInterpreter.from_binary(ensure_python_interpreter(PY310))
    pip = create_pip(python310_interpreter)

    python27_platform = Platform.create("manylinux_2_33_x86_64-cp-27-cp27mu")
    download_dir = os.path.join(str(tmpdir), "downloads")
    pip.spawn_download_distributions(
        target=AbbreviatedPlatform.create(python27_platform),
        requirements=["typing_extensions==3.7.4.2; python_version < '3.8'"],
        download_dir=download_dir,
        transitive=False,
    ).wait()

    assert ["typing_extensions-3.7.4.2-py2-none-any.whl"] == os.listdir(download_dir)


def test_download_platform_markers_issue_1366(
    create_pip,  # type: CreatePip
    tmpdir,  # type: Any
):
    # type: (...) -> None
    assert_download_platform_markers_issue_1366(create_pip, tmpdir)


def test_download_platform_markers_issue_1366_issue_1387(
    create_pip,  # type: CreatePip
    pex_root,  # type: str
    tmpdir,  # type: Any
):
    # type: (...) -> None

    # As noted in https://github.com/pantsbuild/pex/issues/1387, previously, internal env vars were
    # passed by 1st cloning the ambient environment and then adding internal env vars for
    # subprocesses to see. This could lead to duplicate keyword argument errors when env vars we
    # patch - like PEX_ROOT - are also present in the ambient environment. This test verifies we
    # are not tripped up by such ambient environment variables.
    with environment_as(PEX_ROOT=pex_root):
        assert_download_platform_markers_issue_1366(create_pip, tmpdir)


def test_download_platform_markers_issue_1366_indeterminate(
    create_pip,  # type: CreatePip
    tmpdir,  # type: Any
):
    # type: (...) -> None
    python310_interpreter = PythonInterpreter.from_binary(ensure_python_interpreter(PY310))
    pip = create_pip(python310_interpreter)

    python27_platform = Platform.create("manylinux_2_33_x86_64-cp-27-cp27mu")
    download_dir = os.path.join(str(tmpdir), "downloads")

    with pytest.raises(Job.Error) as exc_info:
        pip.spawn_download_distributions(
            target=AbbreviatedPlatform.create(python27_platform),
            requirements=["typing_extensions==3.7.4.2; python_full_version < '3.8'"],
            download_dir=download_dir,
            transitive=False,
        ).wait()
    assert (
        "Failed to resolve for platform manylinux_2_33_x86_64-cp-27-cp27mu. Resolve requires "
        "evaluation of unknown environment marker: 'python_full_version' does not exist in "
        "evaluation environment."
    ) in str(exc_info.value)


def test_download_platform_markers_issue_1488(
    create_pip,  # type: CreatePip
    tmpdir,  # type: Any
):
    # type: (...) -> None

    constraints_file = os.path.join(str(tmpdir), "constraints.txt")
    with open(constraints_file, "w") as fp:
        fp.write("greenlet==1.1.2")

    download_dir = os.path.join(str(tmpdir), "downloads")

    python39_platform = Platform.create("linux-x86_64-cp-39-cp39")
    create_pip(None).spawn_download_distributions(
        target=AbbreviatedPlatform.create(python39_platform, manylinux="manylinux2014"),
        requirements=["SQLAlchemy==1.4.25"],
        constraint_files=[constraints_file],
        download_dir=download_dir,
        transitive=True,
    ).wait()

    assert (
        sorted(
            [
                (
                    "SQLAlchemy-1.4.25-cp39-cp39-manylinux_2_5_x86_64.manylinux1_x86_64"
                    ".manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
                ),
                "greenlet-1.1.2-cp39-cp39-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
            ]
        )
        == sorted(os.listdir(download_dir))
    )


def test_create_confounding_env_vars_issue_1668(
    create_pip,  # type: CreatePip
    tmpdir,  # type: Any
):
    # type: (...) -> None

    download_dir = os.path.join(str(tmpdir), "downloads")
    create_pip(None, PEX_SCRIPT="pex3").spawn_download_distributions(
        requirements=["ansicolors==1.1.8"], download_dir=download_dir
    ).wait()
    assert ["ansicolors-1.1.8-py2.py3-none-any.whl"] == os.listdir(download_dir)
