# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import glob
import os
import re
import shutil
from textwrap import dedent

import pytest

from pex.atomic_directory import atomic_directory
from pex.common import safe_open
from pex.compatibility import urlparse
from pex.dist_metadata import DistMetadata
from pex.pep_503 import ProjectName
from pex.pip.installation import get_pip
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve import resolver_configuration
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing import PY_VER, WheelBuilder, make_env, run_pex_command
from testing.mitmproxy import Proxy

if TYPE_CHECKING:
    from typing import Any, Iterable, Mapping

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class KeyringBackend(object):
    username = attr.ib()  # type: str
    password = attr.ib()  # type: str
    wheel = attr.ib()  # type: str
    project_name = attr.ib(init=False)  # type: ProjectName

    def __attrs_post_init__(self):
        # type: () -> None
        object.__setattr__(self, "project_name", DistMetadata.load(self.wheel).project_name)

    @property
    def basic_auth(self):
        # type: () -> str
        return "{username}:{password}".format(username=self.username, password=self.password)

    @property
    def requirement(self):
        # type: () -> str
        return "{project_name} @ file://{wheel}".format(
            project_name=self.project_name, wheel=self.wheel
        )


@pytest.fixture(scope="session")
def keyring_backend(shared_integration_test_tmpdir):
    # type: (str) -> KeyringBackend

    username = "jake"
    password = "jones"

    project_dir = os.path.join(shared_integration_test_tmpdir, "keyring-backend")
    with atomic_directory(project_dir) as atomic_projectdir:
        if not atomic_projectdir.is_finalized():
            with safe_open(
                os.path.join(atomic_projectdir.work_dir, "pex_test_backend.py"), "w"
            ) as fp:
                fp.write(
                    dedent(
                        """\
                        from keyring.backend import KeyringBackend
                        from keyring import credentials, errors


                        USERNAME = {username!r}
                        PASSWORD = {password!r}


                        class PexTestBackend(KeyringBackend):
                            priority = 9

                            def get_password(self, service, username):
                                return PASSWORD

                            def get_credential(self, service, username=None):
                                return credentials.SimpleCredential(username or USERNAME, PASSWORD)

                            def set_password(service, username, password):
                                raise errors.PasswordSetError("Unsupported.")

                            def delete_password(service, username):
                                raise errors.PasswordDeleteError("Unsupported.")
                        """
                    ).format(username=username, password=password)
                )

            with safe_open(os.path.join(atomic_projectdir.work_dir, "setup.py"), "w") as fp:
                fp.write(
                    dedent(
                        """\
                        from setuptools import setup


                        setup(
                            name="pex_test_backend",
                            version="0.1.0",
                            entry_points={
                                "keyring.backends": [
                                    "pex_test_backend = pex_test_backend",
                                ],
                            },
                            install_requires=["keyring==24.1.1"],
                            py_modules=["pex_test_backend"],
                        )
                        """
                    )
                )

            WheelBuilder(
                source_dir=atomic_projectdir.work_dir, wheel_dir=atomic_projectdir.work_dir
            ).bdist()

    wheels = glob.glob(os.path.join(project_dir, "*.whl"))
    assert 1 == len(wheels)
    return KeyringBackend(username=username, password=password, wheel=wheels[0])


@attr.s(frozen=True)
class KeyringVenv(object):
    backend = attr.ib()  # type: KeyringBackend
    path_element = attr.ib()  # type: str


@pytest.fixture(scope="session")
def keyring_venv(
    shared_integration_test_tmpdir,  # type: str
    keyring_backend,  # type: KeyringBackend
):
    # type: (...) -> KeyringVenv

    keyring_venv_dir = os.path.join(shared_integration_test_tmpdir, "keyring")
    with atomic_directory(keyring_venv_dir) as atomic_venvdir:
        if not atomic_venvdir.is_finalized():
            Virtualenv.create_atomic(
                venv_dir=atomic_venvdir,
                install_pip=InstallationChoice.YES,
                other_installs=[keyring_backend.requirement],
            )
    return KeyringVenv(backend=keyring_backend, path_element=Virtualenv(keyring_venv_dir).bin_dir)


@pytest.fixture
def index_url_info():
    # type: () -> urlparse.ParseResult
    index = os.environ.get("PIP_INDEX_URL", resolver_configuration.PYPI)
    return urlparse.urlparse(index)


@pytest.fixture
def index_reverse_proxy_target(index_url_info):
    # type: (urlparse.ParseResult) -> str
    return str(index_url_info._replace(path="", params="", query="", fragment="").geturl())


@pytest.fixture
def devpi_clean_env():
    # type: () -> Mapping[str, Any]

    # These will be set when tests are run with --devpi, and we want to unset them to
    # ensure our Pex command line config above is what is used.
    return dict(
        _PEX_USE_PIP_CONFIG=None,
        PIP_INDEX_URL=None,
        PIP_TRUSTED_HOST=None,
    )


skip_if_required_keyring_version_not_supported = pytest.mark.skipif(
    PY_VER < (3, 7), reason="The keyring distribution used for this test requires Python `>=3.7`."
)

keyring_provider_pip_versions = pytest.mark.parametrize(
    "pip_version",
    [
        pytest.param(pip_version, id=str(pip_version))
        for pip_version in PipVersion.values()
        # The Pip `--keyring-provider` option is only available starting in Pip 23.1.
        if pip_version >= PipVersion.v23_1 and pip_version.requires_python_applies()
    ],
)


def download_pip_requirements(
    download_dir,  # type: str
    pip_version,  # type: PipVersionValue
    extra_requirements=(),  # type: Iterable[str]
):
    # type: (...) -> None
    requirements = list(map(str, pip_version.requirements))
    requirements.extend(extra_requirements)
    get_pip(resolver=ConfiguredResolver.version(pip_version)).spawn_download_distributions(
        download_dir=download_dir, requirements=requirements
    ).wait()


@skip_if_required_keyring_version_not_supported
@keyring_provider_pip_versions
@pytest.mark.parametrize("use_keyring_provider_option", [False, True])
def test_subprocess_provider(
    proxy,  # type: Proxy
    pip_version,  # type: PipVersionValue
    keyring_venv,  # type: KeyringVenv
    index_url_info,  # type: urlparse.ParseResult
    index_reverse_proxy_target,  # type: str
    devpi_clean_env,  # type: Mapping[str, Any]
    tmpdir,  # type: Any
    use_keyring_provider_option,  # type: bool
):
    # type: (...) -> None

    # N.B.: Pip subprocess keyring support presents a catch-22 for Pex unless there is a
    # non-authenticated source to resolve a non-vendored --pip-version from in the 1st place (since
    # the Pip subprocess keyring backend is only supported in non-vendored versions of Pip); so we
    # use a find-links repo pre-populated with the Pip version we need; just as a user would have
    # to.
    find_links = os.path.join(str(tmpdir), "find-links")
    download_pip_requirements(download_dir=find_links, pip_version=pip_version)

    with proxy.reverse(
        targets=[index_reverse_proxy_target], proxy_auth=keyring_venv.backend.basic_auth
    ) as (port, _):
        pex_root = os.path.join(str(tmpdir), "pex-root")
        proxied_index = str(
            index_url_info._replace(
                scheme="http",
                netloc="{username}@localhost:{port}".format(
                    username=keyring_venv.backend.username, port=port
                ),
            ).geturl()
        )

        # If we are testing the `--keyring-provider`option, then do not put the option into the environment
        # since it will be passed on the command-line.
        new_path = os.pathsep.join((keyring_venv.path_element, os.environ.get("PATH", os.defpath)))
        if use_keyring_provider_option:
            env = make_env(PATH=new_path, **devpi_clean_env)
        else:
            env = make_env(PIP_KEYRING_PROVIDER="subprocess", PATH=new_path, **devpi_clean_env)

        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--no-pypi",
                "--index",
                proxied_index,
                "--find-links",
                find_links,
                "--pip-version",
                str(pip_version),
                "--keyring-provider=subprocess"
                if use_keyring_provider_option
                else "--use-pip-config",
                "cowsay==5.0",
                "-c",
                "cowsay",
                "--",
                "Subprocess Auth!",
            ],
            env=env,
        ).assert_success(expected_output_re=r"^.*\| Subprocess Auth! \|.*$", re_flags=re.DOTALL)


@skip_if_required_keyring_version_not_supported
@keyring_provider_pip_versions
@pytest.mark.parametrize("use_keyring_provider_option", [False, True])
def test_import_provider(
    proxy,  # type: Proxy
    pip_version,  # type: PipVersionValue
    keyring_venv,  # type: KeyringVenv
    index_url_info,  # type: urlparse.ParseResult
    index_reverse_proxy_target,  # type: str
    devpi_clean_env,  # type: Mapping[str, Any]
    tmpdir,  # type: Any
    use_keyring_provider_option,  # type: bool
):
    # type: (...) -> None

    # N.B.: Pip keyring support presents a catch-22 unless there is a non-authenticated source to
    # resolve the keyring distributions from in the 1st place; so we use a find-links repo
    # pre-populated with the keyring dependencies we need to authenticate; just as a user would
    # have to.
    find_links = os.path.join(str(tmpdir), "find-links")
    download_pip_requirements(
        download_dir=find_links,
        pip_version=pip_version,
        extra_requirements=[keyring_venv.backend.wheel],
    )
    shutil.copy(keyring_venv.backend.wheel, find_links)

    with proxy.reverse(
        targets=[index_reverse_proxy_target], proxy_auth=keyring_venv.backend.basic_auth
    ) as (port, _):
        pex_root = os.path.join(str(tmpdir), "pex-root")
        proxied_index = str(
            index_url_info._replace(
                scheme="http",
                netloc="localhost:{port}".format(port=port),
            ).geturl()
        )

        # If we are testing the `--keyring-provider`option, then do not put the option into the environment
        # since it will be passed on the command-line.
        if use_keyring_provider_option:
            env = make_env(**devpi_clean_env)
        else:
            env = make_env(PIP_KEYRING_PROVIDER="import", **devpi_clean_env)

        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--no-pypi",
                "--index",
                proxied_index,
                "--find-links",
                find_links,
                "--extra-pip-requirement",
                str(keyring_venv.backend.project_name),
                "--pip-version",
                str(pip_version),
                "--keyring-provider=import" if use_keyring_provider_option else "--use-pip-config",
                "cowsay==5.0",
                "-c",
                "cowsay",
                "--",
                "Import Auth!",
            ],
            env=env,
        ).assert_success(expected_output_re=r"^.*\| Import Auth! \|.*$", re_flags=re.DOTALL)
