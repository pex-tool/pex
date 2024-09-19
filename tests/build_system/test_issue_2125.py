# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
from textwrap import dedent

from pex.build_system import pep_517
from pex.common import safe_open
from pex.pip.version import PipVersion
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.resolver_configuration import PipConfiguration
from pex.targets import LocalInterpreter
from pex.typing import TYPE_CHECKING
from testing.dist_metadata import create_dist_metadata

if TYPE_CHECKING:
    from typing import Any


def test_missing_get_requires_for_build_wheel(tmpdir):
    # type: (Any) -> None

    project_directory = os.path.join(str(tmpdir), "project")

    dist_info_dir = os.path.join(project_directory, "foo-0.1.0.dist-info")
    metadata = os.path.join(dist_info_dir, "METADATA")
    with safe_open(metadata, "w") as fp:
        fp.write(
            dedent(
                """\
                Metadata-Version: 1.2
                Name: foo
                Version: 0.1.0
                Requires-Dist: conscript
                Requires-Dist: pex>=2.1.134
                Requires-Python: >=3.11
                """
            )
        )

    build_backend = os.path.join(project_directory, "pep517", "hooks.py")
    with safe_open(build_backend, "w") as fp:
        fp.write(
            dedent(
                """\
                from __future__ import print_function

                import os
                import shutil
                import sys

                import colors


                def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
                    print(
                        colors.green("Using pre-prepared metadata in {dist_info_dir}."),
                        file=sys.stderr
                    )
                    shutil.move({dist_info_dir!r}, metadata_directory)
                    return os.path.relpath({metadata!r}, {project_directory!r})
                """
            ).format(
                dist_info_dir=dist_info_dir, metadata=metadata, project_directory=project_directory
            )
        )

    pyproject_toml = os.path.join(project_directory, "pyproject.toml")
    with open(pyproject_toml, "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["ansicolors==1.1.8"]
                build-backend = "hooks"
                backend-path = ["pep517"]
                """
            )
        )

    pip_version = PipVersion.DEFAULT
    dist_metadata = pep_517.spawn_prepare_metadata(
        project_directory=project_directory,
        pip_version=pip_version,
        target=LocalInterpreter.create(),
        resolver=ConfiguredResolver(PipConfiguration(version=pip_version)),
    ).await_result()

    assert (
        create_dist_metadata(
            project_name="foo",
            version="0.1.0",
            requires_python=">=3.11",
            requires_dists=("conscript", "pex>=2.1.134"),
        )
        == dist_metadata
    )
