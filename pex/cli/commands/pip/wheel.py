# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
from argparse import _ActionsContainer
from collections import OrderedDict

from pex.cli.command import BuildTimeCommand
from pex.cli.commands.pip import core
from pex.cli.commands.pip.core import LocalProject, SourceDist, WheelDist
from pex.common import safe_copy, safe_mkdir
from pex.resolver import BuildRequest
from pex.result import Ok, Result, try_
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import List


class Wheel(BuildTimeCommand):
    """Materialize wheel files instead of resolving them into a PEX."""

    @classmethod
    def add_extra_arguments(cls, parser):
        # type: (_ActionsContainer) -> None
        parser.add_argument(
            "-d",
            "--dest-dir",
            metavar="PATH",
            required=True,
            help="The path to materialize wheels to.",
        )
        core.register_options(parser)

    def run(self):
        # type: () -> Result

        configuration = core.configure(self.options)
        dists = try_(core.download_distributions(configuration))

        wheels = OrderedDict()  # type: OrderedDict[str, str]
        local_projects = []  # type: List[LocalProject]
        sdists = []  # type: List[SourceDist]
        for dist in dists:
            if isinstance(dist, WheelDist):
                wheels[os.path.basename(dist.path)] = dist.path
            elif isinstance(dist, LocalProject):
                local_projects.append(dist)
            else:
                sdists.append(dist)

        if local_projects or sdists:
            build_requests = []  # type: List[BuildRequest]
            for target in configuration.resolve_targets().unique_targets():
                for local_project in local_projects:
                    build_requests.append(
                        BuildRequest.for_directory(
                            target=target,
                            source_path=local_project.path,
                            editable=local_project.editable,
                        )
                    )
                for sdist in sdists:
                    build_requests.append(
                        BuildRequest.for_file(
                            target=target,
                            source_path=sdist.path,
                            subdirectory=sdist.subdirectory,
                        )
                    )
            wheels.update(
                (os.path.basename(wheel), wheel)
                for wheel in try_(core.build_wheels(configuration, build_requests))
            )

        safe_mkdir(self.options.dest_dir)
        for wheel in wheels.values():
            safe_copy(wheel, os.path.join(self.options.dest_dir, os.path.basename(wheel)))

        return Ok()
