# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.dist_metadata import Requirement
from pex.pep_427 import InstallableType
from pex.pip.configuration import PipConfiguration, ResolverVersion
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve.package_repository import ReposConfiguration
from pex.resolve.resolvers import Resolver, ResolveResult
from pex.targets import Targets
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


_DEFAULT_REPOS = ReposConfiguration.create()


@attr.s(frozen=True)
class PipResolver(Resolver):
    @classmethod
    def version(cls, pip_version):
        # type: (PipVersionValue) -> PipResolver
        return cls(
            PipConfiguration(
                version=pip_version, resolver_version=ResolverVersion.default(pip_version)
            )
        )

    @classmethod
    def default(cls):
        # type: () -> PipResolver
        return cls.version(PipVersion.DEFAULT)

    def is_default_repos(self):
        # type: () -> bool
        return self.pip_configuration.repos_configuration == _DEFAULT_REPOS

    def use_system_time(self):
        # type: () -> bool
        return self.pip_configuration.build_configuration.use_system_time

    def resolve_requirements(
        self,
        requirements,  # type: Iterable[str]
        targets=Targets(),  # type: Targets
        pip_version=None,  # type: Optional[PipVersionValue]
        transitive=None,  # type: Optional[bool]
        extra_resolver_requirements=None,  # type: Optional[Tuple[Requirement, ...]]
        result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
        constraint_files=None,  # type: Optional[Iterable[str]]
        compile=False,  # type: bool
        ignore_errors=False,  # type: bool
    ):
        # type: (...) -> ResolveResult
        from pex import resolver

        return resolver.resolve(
            targets=targets,
            requirements=requirements,
            constraint_files=constraint_files,
            pip_configuration=attr.evolve(
                self.pip_configuration,
                transitive=(
                    transitive if transitive is not None else self.pip_configuration.transitive
                ),
                version=pip_version or self.pip_configuration.version,
                extra_requirements=(
                    extra_resolver_requirements
                    if extra_resolver_requirements is not None
                    else self.pip_configuration.extra_requirements
                ),
            ),
            compile=compile,
            ignore_errors=ignore_errors,
            verify_wheels=True,
            result_type=result_type,
        )
