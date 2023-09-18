# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import json
import os
import shutil
import warnings

import pytest

from pex.common import safe_rmtree
from pex.interpreter import PythonInterpreter
from pex.jobs import Job
from pex.pip.installation import _PIP, PipInstallation, get_pip
from pex.pip.tool import PackageIndexConfiguration, Pip
from pex.pip.version import PipVersion, PipVersionValue
from pex.platforms import Platform
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.targets import AbbreviatedPlatform, LocalInterpreter, Target
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from testing import IS_LINUX, PY310, ensure_python_interpreter, environment_as

if TYPE_CHECKING:
    from typing import Any, Iterator, Optional, Protocol

    class CreatePip(Protocol):
        def __call__(
            self,
            interpreter,  # type: Optional[PythonInterpreter]
            version=PipVersion.DEFAULT,  # type: PipVersionValue
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

    def create_pip(
        interpreter,  # type: Optional[PythonInterpreter]
        version=PipVersion.DEFAULT,  # type: PipVersionValue
        **extra_env  # type: str
    ):
        # type: (...) -> Pip
        with ENV.patch(PEX_ROOT=pex_root, **extra_env):
            return get_pip(
                interpreter=interpreter, version=version, resolver=ConfiguredResolver.default()
            )

    yield create_pip


all_pip_versions = pytest.mark.parametrize(
    "version", [pytest.param(version, id=str(version)) for version in PipVersion.values()]
)


applicable_pip_versions = pytest.mark.parametrize(
    "version",
    [
        pytest.param(version, id=str(version))
        for version in PipVersion.values()
        if version.requires_python_applies()
    ],
)


@applicable_pip_versions
def test_no_duplicate_constraints_pex_warnings(
    create_pip,  # type: CreatePip
    version,  # type: PipVersionValue
    current_interpreter,  # type: PythonInterpreter
):
    # type: (...) -> None
    with warnings.catch_warnings(record=True) as events:
        pip = create_pip(current_interpreter, version=version)

    pip.spawn_debug(platform=current_interpreter.platform).wait()

    assert 0 == len([event for event in events if "constraints.txt" in str(event)]), (
        "Expected no duplicate constraints warnings to be emitted when creating a Pip venv but "
        "found\n{}".format("\n".join(map(str, events)))
    )


@pytest.mark.skipif(
    not IS_LINUX
    or not any(
        (
            "manylinux2014_x86_64" == platform.platform
            for platform in PythonInterpreter.get().supported_platforms
        )
    ),
    reason="Test requires a manylinux2014_x86_64 compatible interpreter.",
)
@applicable_pip_versions
def test_download_platform_issues_1355(
    create_pip,  # type: CreatePip
    version,  # type: PipVersionValue
    py38,  # type: PythonInterpreter
    tmpdir,  # type: Any
):
    # type: (...) -> None
    pip = create_pip(py38, version=version)
    download_dir = os.path.join(str(tmpdir), "downloads")

    def download_pyarrow(
        target=None,  # type: Optional[Target]
        package_index_configuration=None,  # type: Optional[PackageIndexConfiguration]
    ):
        # type: (...) -> Job
        safe_rmtree(download_dir)
        return pip.spawn_download_distributions(
            download_dir=download_dir,
            requirements=["pyarrow==4.0.1"],
            transitive=False,
            target=target,
            package_index_configuration=package_index_configuration,
        )

    def assert_pyarrow_downloaded(
        expected_wheel,  # type: str
        target=None,  # type: Optional[Target]
    ):
        # type: (...) -> None
        download_pyarrow(target=target).wait()
        assert [expected_wheel] == os.listdir(download_dir)

    assert_pyarrow_downloaded(
        "pyarrow-4.0.1-cp38-cp38-manylinux2014_x86_64.whl", target=LocalInterpreter.create(py38)
    )
    assert_pyarrow_downloaded(
        "pyarrow-4.0.1-cp38-cp38-manylinux2010_x86_64.whl",
        target=AbbreviatedPlatform.create(
            Platform.create("linux-x86_64-cp-38-cp38"), manylinux="manylinux2010"
        ),
    )


def assert_download_platform_markers_issue_1366(
    create_pip,  # type: CreatePip
    version,  # type: PipVersionValue
    tmpdir,  # type: Any
):
    # type: (...) -> None
    python310_interpreter = PythonInterpreter.from_binary(ensure_python_interpreter(PY310))
    pip = create_pip(python310_interpreter, version=version)

    python27_platform = Platform.create("manylinux_2_33_x86_64-cp-27-cp27mu")
    download_dir = os.path.join(str(tmpdir), "downloads")
    pip.spawn_download_distributions(
        target=AbbreviatedPlatform.create(python27_platform),
        requirements=["typing_extensions==3.7.4.2; python_version < '3.8'"],
        download_dir=download_dir,
        transitive=False,
    ).wait()

    assert ["typing_extensions-3.7.4.2-py2-none-any.whl"] == os.listdir(download_dir)


@all_pip_versions
def test_download_platform_markers_issue_1366(
    create_pip,  # type: CreatePip
    version,  # type: PipVersionValue
    tmpdir,  # type: Any
):
    # type: (...) -> None
    assert_download_platform_markers_issue_1366(create_pip, version, tmpdir)


@all_pip_versions
def test_download_platform_markers_issue_1366_issue_1387(
    create_pip,  # type: CreatePip
    version,  # type: PipVersionValue
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
        assert_download_platform_markers_issue_1366(create_pip, version, tmpdir)


@all_pip_versions
def test_download_platform_markers_issue_1366_indeterminate(
    create_pip,  # type: CreatePip
    version,  # type: PipVersionValue
    tmpdir,  # type: Any
):
    # type: (...) -> None
    python310_interpreter = PythonInterpreter.from_binary(ensure_python_interpreter(PY310))
    pip = create_pip(python310_interpreter, version=version)

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


@applicable_pip_versions
def test_download_platform_markers_issue_1488(
    create_pip,  # type: CreatePip
    version,  # type: PipVersionValue
    tmpdir,  # type: Any
):
    # type: (...) -> None

    constraints_file = os.path.join(str(tmpdir), "constraints.txt")
    with open(constraints_file, "w") as fp:
        fp.write("greenlet==1.1.2")

    download_dir = os.path.join(str(tmpdir), "downloads")

    python39_platform = Platform.create("linux-x86_64-cp-39-cp39")
    create_pip(None, version=version).spawn_download_distributions(
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


@applicable_pip_versions
def test_create_confounding_env_vars_issue_1668(
    create_pip,  # type: CreatePip
    version,  # type: PipVersionValue
    tmpdir,  # type: Any
):
    # type: (...) -> None

    download_dir = os.path.join(str(tmpdir), "downloads")
    create_pip(None, version=version, PEX_SCRIPT="pex3").spawn_download_distributions(
        requirements=["ansicolors==1.1.8"], download_dir=download_dir
    ).wait()
    assert ["ansicolors-1.1.8-py2.py3-none-any.whl"] == os.listdir(download_dir)


def test_pip_pex_interpreter_venv_hash_issue_1885(
    create_pip,  # type: CreatePip
    current_interpreter,  # type: PythonInterpreter
    tmpdir,  # type: Any
):
    # type: (...) -> None
    """This test is under the test_pip module because the resolver
    doesn't allow the user to control the pip.pex interpreter constraints, so those intperpreter
    constraints can't feed into the venv_dir hash. Therefore if
    PEX_PYTHON_PATH is present and contains symlinks that aren't resolved the wrong pip pex venv
    may end up being invoked by resolver.resolve because the pip.pex venv dir collisions.

    This tests that that doesn't happen.
    """
    # Remove any existing pip.pex which may exist as a result of other test suites.
    installation = PipInstallation(
        interpreter=current_interpreter,
        version=PipVersion.DEFAULT,
    )
    _PIP.pop(installation, None)
    binary = current_interpreter.binary
    binary_link = os.path.join(str(tmpdir), "python")
    os.symlink(binary, binary_link)
    pip_w_linked_ppp = create_pip(current_interpreter, PEX_PYTHON_PATH=binary_link)
    print("binary link real path resolves to: {}".format(os.path.realpath(binary_link)))
    venv_contents_hash = hashlib.sha1(
        json.dumps(
            {
                "pex_path": {},
                "PEX_PYTHON_PATH": (binary_link,),
                "interpreter": os.path.realpath(binary_link),
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert venv_contents_hash in pip_w_linked_ppp._pip.venv_dir


@applicable_pip_versions
def test_use_pip_config(
    create_pip,  # type: CreatePip
    version,  # type: PipVersionValue
    current_interpreter,  # type: PythonInterpreter
    tmpdir,  # type: Any
):
    # type: (...) -> None

    pip = create_pip(current_interpreter, version=version)

    download_dir = os.path.join(str(tmpdir), "downloads")
    assert not os.path.exists(download_dir)

    with ENV.patch(PIP_PYTHON_VERSION="invalid") as env, environment_as(**env):
        assert "invalid" == os.environ["PIP_PYTHON_VERSION"]
        job = pip.spawn_download_distributions(
            download_dir=download_dir, requirements=["ansicolors==1.1.8"]
        )
        assert "--isolated" in job._command
        job.wait()
        assert ["ansicolors-1.1.8-py2.py3-none-any.whl"] == os.listdir(download_dir)

        shutil.rmtree(download_dir)
        package_index_configuration = PackageIndexConfiguration.create(use_pip_config=True)
        job = pip.spawn_download_distributions(
            download_dir=download_dir,
            requirements=["ansicolors==1.1.8"],
            package_index_configuration=package_index_configuration,
        )
        assert "--isolated" not in job._command
        with pytest.raises(Job.Error) as exc:
            job.wait()
        assert not os.path.exists(download_dir)
        assert "invalid --python-version value: 'invalid'" in str(exc.value.stderr)
