# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import json
import os
import re
import shutil
import warnings
from typing import Dict

import pytest

from pex.common import environment_as, safe_rmtree
from pex.dist_metadata import Distribution, Requirement
from pex.interpreter import PythonInterpreter
from pex.jobs import Job
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex_warnings import PEXWarning
from pex.pip.installation import _PIP, PipInstallation, get_pip
from pex.pip.tool import PackageIndexConfiguration, Pip
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve import abbreviated_platforms
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.resolver_configuration import ResolverVersion
from pex.targets import AbbreviatedPlatform, LocalInterpreter, Target
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from pex.venv.virtualenv import Virtualenv
from testing import IS_LINUX, PY310, ensure_python_interpreter
from testing.pytest.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, Optional, Protocol

    class CreatePip(Protocol):
        def __call__(
            self,
            interpreter,  # type: Optional[PythonInterpreter]
            version=PipVersion.DEFAULT,  # type: PipVersionValue
            extra_requirements=(),  # type: Iterable[Requirement]
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
    # type: (Tempdir) -> str
    return tmpdir.join("pex_root")


@pytest.fixture
def create_pip(pex_root):
    # type: (str) -> Iterator[CreatePip]

    def create_pip(
        interpreter,  # type: Optional[PythonInterpreter]
        version=PipVersion.DEFAULT,  # type: PipVersionValue
        extra_requirements=(),  # type: Iterable[Requirement]
        **extra_env  # type: str
    ):
        # type: (...) -> Pip
        with ENV.patch(PEX_ROOT=pex_root, **extra_env):
            return get_pip(
                interpreter=interpreter,
                version=version,
                resolver=ConfiguredResolver.default(),
                extra_requirements=tuple(extra_requirements),
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
        create_pip(current_interpreter, version=version)

    assert 0 == len([event for event in events if "constraints.txt" in str(event)]), (
        "Expected no duplicate constraints warnings to be emitted when creating a Pip venv but "
        "found\n{}".format("\n".join(map(str, events)))
    )


def package_index_configuration(
    pip_version,  # type: PipVersionValue
    use_pip_config=False,  # type: bool
    keyring_provider=None,  # type: Optional[str]
):
    # type: (...) -> PackageIndexConfiguration
    if pip_version is PipVersion.v23_2:
        # N.B.: Pip 23.2 has a bug handling PEP-658 metadata with the legacy resolver; so we use the
        # 2020 resolver to work around. See: https://github.com/pypa/pip/issues/12156
        return PackageIndexConfiguration.create(
            pip_version,
            resolver_version=ResolverVersion.PIP_2020,
            use_pip_config=use_pip_config,
            keyring_provider=keyring_provider,
        )
    return PackageIndexConfiguration.create(
        use_pip_config=use_pip_config, keyring_provider=keyring_provider
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

    def download_pyarrow(target=None):
        # type: (Optional[Target]) -> Job
        safe_rmtree(download_dir)
        return pip.spawn_download_distributions(
            download_dir=download_dir,
            requirements=["pyarrow==4.0.1"],
            transitive=False,
            target=target,
            package_index_configuration=package_index_configuration(pip.version),
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
            abbreviated_platforms.create("linux-x86_64-cp-38-cp38", manylinux="manylinux2010")
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

    python27_platform = abbreviated_platforms.create("manylinux_2_33_x86_64-cp-27-cp27mu")
    download_dir = os.path.join(str(tmpdir), "downloads")
    pip.spawn_download_distributions(
        target=AbbreviatedPlatform.create(python27_platform),
        requirements=["typing_extensions==3.7.4.2; python_version < '3.8'"],
        download_dir=download_dir,
        transitive=False,
        package_index_configuration=package_index_configuration(pip.version),
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

    # As noted in https://github.com/pex-tool/pex/issues/1387, previously, internal env vars were
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

    target = AbbreviatedPlatform.create(
        abbreviated_platforms.create("manylinux_2_33_x86_64-cp-27-cp27mu")
    )
    download_dir = os.path.join(str(tmpdir), "downloads")

    with pytest.raises(Job.Error) as exc_info:
        pip.spawn_download_distributions(
            target=target,
            requirements=["typing_extensions==3.7.4.2; python_full_version < '3.8'"],
            download_dir=download_dir,
            transitive=False,
        ).wait()
    assert (
        "Failed to resolve for {target_description}. Resolve requires "
        "evaluation of unknown environment marker: 'python_full_version' does not exist in "
        "evaluation environment."
    ).format(target_description=target.render_description()) in str(exc_info.value), str(
        exc_info.value
    )


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

    python39_platform = abbreviated_platforms.create(
        "linux-x86_64-cp-39-cp39", manylinux="manylinux2014"
    )
    create_pip(None, version=version).spawn_download_distributions(
        target=AbbreviatedPlatform.create(python39_platform),
        requirements=["SQLAlchemy==1.4.25"],
        constraint_files=[constraints_file],
        download_dir=download_dir,
        transitive=True,
        package_index_configuration=package_index_configuration(version),
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
        requirements=["ansicolors==1.1.8"],
        download_dir=download_dir,
        package_index_configuration=package_index_configuration(pip_version=version),
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
        extra_requirements=(),
        use_system_time=False,
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
    assert venv_contents_hash in pip_w_linked_ppp.venv_dir


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
            download_dir=download_dir,
            requirements=["ansicolors==1.1.8"],
            package_index_configuration=package_index_configuration(pip_version=version),
        )
        assert "--isolated" in job._command
        job.wait()
        assert ["ansicolors-1.1.8-py2.py3-none-any.whl"] == os.listdir(download_dir)

        shutil.rmtree(download_dir)
        job = pip.spawn_download_distributions(
            download_dir=download_dir,
            requirements=["ansicolors==1.1.8"],
            package_index_configuration=package_index_configuration(
                pip_version=version, use_pip_config=True
            ),
        )
        assert "--isolated" not in job._command, "\n".join(job._command)
        with pytest.raises(Job.Error) as exc:
            job.wait()
        assert not os.path.exists(download_dir)
        assert "invalid --python-version value: 'invalid'" in str(exc.value.stderr)


@applicable_pip_versions
def test_keyring_provider(
    create_pip,  # type: CreatePip
    version,  # type: PipVersionValue
    current_interpreter,  # type: PythonInterpreter
    tmpdir,  # type: Any
):
    # type: (...) -> None

    has_keyring_provider_option = version >= PipVersion.v23_1

    pip = create_pip(current_interpreter, version=version)

    download_dir = os.path.join(str(tmpdir), "downloads")
    assert not os.path.exists(download_dir)

    with ENV.patch(PIP_KEYRING_PROVIDER="invalid") as env, environment_as(
        **env
    ), warnings.catch_warnings(record=True) as events:
        assert "invalid" == os.environ["PIP_KEYRING_PROVIDER"]
        job = pip.spawn_download_distributions(
            download_dir=download_dir,
            requirements=["ansicolors==1.1.8"],
            package_index_configuration=package_index_configuration(
                pip_version=version, keyring_provider="auto"
            ),
        )

        cmd_args = tuple(job._command)
        if has_keyring_provider_option:
            assert "--keyring-provider" in cmd_args
            keyring_arg_index = job._command.index("--keyring-provider")
            assert cmd_args[keyring_arg_index : keyring_arg_index + 2] == (
                "--keyring-provider",
                "auto",
            )
            with pytest.raises(Job.Error) as exc:
                job.wait()
        else:
            assert "--keyring-provider" not in cmd_args
            job.wait()
            assert len(events) == 1
            assert PEXWarning == events[0].category
            message = str(events[0].message).replace("\n", " ")
            assert "does not support the `--keyring-provider` option" in message


@applicable_pip_versions
def test_extra_pip_requirements_pip_not_allowed(
    create_pip,  # type: CreatePip
    version,  # type: PipVersionValue
    current_interpreter,  # type: PythonInterpreter
):
    # type: (...) -> None

    with pytest.raises(
        ValueError,
        match=re.escape(
            "An `--extra-pip-requirement` cannot be used to override the Pip version; use "
            "`--pip-version` to select a supported Pip version instead. Given: pip~=24.0"
        ),
    ):
        create_pip(
            current_interpreter,
            version=version,
            extra_requirements=[Requirement.parse("pip~=24.0")],
        )


def index_pip_distributions(
    create_pip,  # type: CreatePip
    current_interpreter,  # type: PythonInterpreter
    version,  # type: PipVersionValue
    extra_requirement,  # type: str
):
    # type: (...) -> Dict[ProjectName, Distribution]

    pip = create_pip(
        current_interpreter,
        version=version,
        extra_requirements=[Requirement.parse(extra_requirement)],
    )
    dists_by_project_name = {
        dist.metadata.project_name: dist
        for dist in Virtualenv(pip.venv_dir).iter_distributions(rescan=True)
    }

    # N.B.: We avoid testing the full version (local segment) since our vendored Pip is
    # 20.3.4+patched. Testing the release (`<major>.<minor>.<patch>`) gets us the assurance we want
    # here.
    assert (
        version.version.parsed_version.release
        == dists_by_project_name.pop(ProjectName("pip")).metadata.version.parsed_version.release
    )

    return dists_by_project_name


@applicable_pip_versions
def test_extra_pip_requirements_setuptools_override(
    create_pip,  # type: CreatePip
    version,  # type: PipVersionValue
    current_interpreter,  # type: PythonInterpreter
):
    # type: (...) -> None

    # N.B.: 44.0.0 is the oldest wheel version used by any of our supported `--pip-version`s.
    custom_setuptools_version = Version("43.0.0")
    custom_setuptools_requirement = "setuptools=={version}".format(
        version=custom_setuptools_version
    )

    if PipVersion.VENDORED is version:
        with pytest.raises(
            ValueError,
            match=re.escape(
                "An `--extra-pip-requirement` cannot be used to override the setuptools version "
                "for vendored Pip. If you need a custom setuptools you need to use `--pip-version` "
                "to select a non-vendored Pip version. Given: {setuptools_requirement}".format(
                    setuptools_requirement=custom_setuptools_requirement
                )
            ),
        ):
            create_pip(
                current_interpreter,
                version=version,
                extra_requirements=[Requirement.parse(custom_setuptools_requirement)],
            )
        return

    dists_by_project_name = index_pip_distributions(
        create_pip, current_interpreter, version, custom_setuptools_requirement
    )
    assert dists_by_project_name.pop(ProjectName("wheel")) in version.wheel_requirement

    setuptools = dists_by_project_name.pop(ProjectName("setuptools"))
    assert setuptools not in version.setuptools_requirement
    assert custom_setuptools_version == setuptools.metadata.version


@applicable_pip_versions
def test_extra_pip_requirements_wheel_override(
    create_pip,  # type: CreatePip
    version,  # type: PipVersionValue
    current_interpreter,  # type: PythonInterpreter
):
    # type: (...) -> None

    # N.B.: 0.37.1 is the oldest wheel version used by any of our supported `--pip-version`s.
    custom_wheel_version = Version("0.37.0")
    custom_wheel_requirement = "wheel=={version}".format(version=custom_wheel_version)

    if PipVersion.VENDORED is version:
        with pytest.raises(
            ValueError,
            match=re.escape(
                "An `--extra-pip-requirement` cannot be used to override the wheel version "
                "for vendored Pip. If you need a custom wheel version you need to use "
                "`--pip-version` to select a non-vendored Pip version. "
                "Given: {wheel_requirement}".format(wheel_requirement=custom_wheel_requirement)
            ),
        ):
            create_pip(
                current_interpreter,
                version=version,
                extra_requirements=[Requirement.parse(custom_wheel_requirement)],
            )
        return

    dists_by_project_name = index_pip_distributions(
        create_pip, current_interpreter, version, custom_wheel_requirement
    )
    assert dists_by_project_name.pop(ProjectName("setuptools")) in version.setuptools_requirement

    wheel = dists_by_project_name.pop(ProjectName("wheel"))
    assert wheel not in version.wheel_requirement
    assert custom_wheel_version == wheel.metadata.version
