# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil

from pex.build_system import pep_517
from pex.common import safe_mkdir, safe_mkdtemp
from pex.pip.version import PipVersionValue
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.resolvers import Resolver
from pex.result import try_
from pex.targets import LocalInterpreter
from pex.typing import TYPE_CHECKING
from testing import built_wheel, make_project

if TYPE_CHECKING:
    from typing import List, Optional, Text

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class FindLinksRepo(object):
    @classmethod
    def create(
        cls,
        path,  # type: str
        pip_version,  # type: PipVersionValue
    ):
        # type: (...) -> FindLinksRepo
        safe_mkdir(path, clean=True)
        return cls(path=path, resolver=ConfiguredResolver.version(pip_version))

    path = attr.ib()  # type: str
    resolver = attr.ib()  # type: Resolver

    def host(self, distribution):
        # type: (Text) -> None
        shutil.copy(distribution, os.path.join(self.path, os.path.basename(distribution)))

    def make_wheel(
        self,
        project_name,  # type: str
        version,  # type: str
        install_reqs=None,  # type: Optional[List[str]]
    ):
        # type: (...) -> None
        with built_wheel(
            name=project_name, version=version, universal=True, install_reqs=install_reqs
        ) as wheel:
            self.host(wheel)

    def make_sdist(
        self,
        project_name,  # type: str
        version,  # type: str
        install_reqs=None,  # type: Optional[List[str]]
    ):
        # type: (...) -> None
        with make_project(name=project_name, version=version, install_reqs=install_reqs) as project:
            self.host(
                try_(
                    pep_517.build_sdist(
                        project_directory=project,
                        dist_dir=safe_mkdtemp(),
                        target=LocalInterpreter.create(),
                        resolver=self.resolver,
                    )
                )
            )
