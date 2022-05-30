# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess

from pex.build_system.pep_518 import BuildSystem, load_build_system
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.resolver_configuration import PipConfiguration, ReposConfiguration
from pex.testing import make_env, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_load_build_system_pyproject_custom_repos(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    build_system = load_build_system(ConfiguredResolver.default(), pex_project_dir)
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
    custom_resolver = ConfiguredResolver(PipConfiguration(repos_configuration=repos_configuration))
    build_system = load_build_system(custom_resolver, pex_project_dir)
    assert isinstance(build_system, BuildSystem)
    subprocess.check_call(
        args=[build_system.pex, "-c", "import {}".format(build_system.build_backend)]
    )
