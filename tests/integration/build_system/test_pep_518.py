# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess

from pex.build_system.pep_518 import BuildSystem, load_build_system
from pex.pip.version import PipVersion
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.resolver_configuration import PipConfiguration, ReposConfiguration
from pex.targets import LocalInterpreter
from pex.typing import TYPE_CHECKING
from testing import make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any


def test_load_build_system_pyproject_custom_repos(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    current_target = LocalInterpreter.create()
    pip_version = (
        PipVersion.v22_2_2
        if PipVersion.v22_2_2.requires_python_applies(current_target)
        else PipVersion.DEFAULT
    )
    build_system = load_build_system(
        current_target,
        ConfiguredResolver(PipConfiguration(version=pip_version)),
        pex_project_dir,
    )
    assert isinstance(build_system, BuildSystem)

    # Verify that we can still resolve a build backend even when our toml lock is unuseable.
    repository_pex = os.path.join(str(tmpdir), "repository.pex")
    run_pex_command(
        args=["--include-tools", "-o", repository_pex] + list(build_system.requires)
    ).assert_success()

    find_links = os.path.join(str(tmpdir), "find_links")
    subprocess.check_call(
        args=[repository_pex, "repository", "extract", "--find-links", find_links],
        env=make_env(PEX_TOOLS=1),
    )

    repos_configuration = ReposConfiguration.create(find_links=[find_links])
    assert not repos_configuration.indexes
    custom_resolver = ConfiguredResolver(
        PipConfiguration(repos_configuration=repos_configuration, version=pip_version)
    )
    build_system = load_build_system(current_target, custom_resolver, pex_project_dir)
    assert isinstance(build_system, BuildSystem)
    subprocess.check_call(
        args=[build_system.venv_pex.pex, "-c", "import {}".format(build_system.build_backend)],
        env=build_system.env,
    )
