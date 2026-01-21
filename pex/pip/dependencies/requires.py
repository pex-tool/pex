# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import logging
import sys

logger = logging.getLogger(__name__)


def patch():
    from pip._vendor.pkg_resources import Requirement

    from pex.common import pluralize
    from pex.dist_metadata import Requirement as PexRequirement
    from pex.pep_508 import MarkerEnvironment
    from pex.pip.dependencies import PatchContext
    from pex.resolve.target_system import UniversalTarget
    from pex.typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from typing import Dict, Optional, Sequence

    patch_context = PatchContext.load()
    dependency_configuration = patch_context.dependency_configuration
    target = patch_context.target

    marker_environment = None  # type: Optional[Dict[str, str]]
    if isinstance(target, MarkerEnvironment):
        marker_environment = target.as_dict()

    def are_exhaustive(
        universal_target,  # type: UniversalTarget
        overrides,  # type: Sequence[Requirement]
    ):
        # type: (...) -> bool

        markers = [override.marker for override in overrides if override.marker]
        if len(markers) < len(overrides):
            # We have at least one override without a marker; i.e.: the override always applies.
            return True

        return universal_target.are_exhaustive(markers=markers)

    def create_requires(orig_requires):
        def requires(self, *args, **kwargs):
            modified_requires = []
            orig = orig_requires(self, *args, **kwargs)
            for req in orig:
                requirement = PexRequirement.parse(str(req), source=repr(self))
                excluded_by = dependency_configuration.excluded_by(requirement)
                if excluded_by:
                    logger.debug(
                        "[{type}: patched {orig_requires}] Excluded {dep} from {dist} due to "
                        "Pex-configured excludes: {excludes}".format(
                            orig_requires=orig_requires,
                            type=type(self),
                            dep=repr(str(req)),
                            dist=self,
                            excludes=" and ".join(repr(str(exclude)) for exclude in excluded_by),
                        )
                    )
                    continue

                overrides = list(dependency_configuration.overrides_for(requirement))
                if marker_environment:
                    overrides = [
                        override
                        for override in overrides
                        if not override.marker or override.marker.evaluate(marker_environment)
                    ]
                elif overrides and not are_exhaustive(patch_context.target, overrides):
                    overrides.append(req)

                if overrides:
                    logger.debug(
                        "[{type}: patched {orig_requires}] Overrode {dep} from {dist} with "
                        "{count} Pex-configured {overrides}:\n{requirements}".format(
                            orig_requires=orig_requires,
                            type=type(self),
                            dep=repr(str(req)),
                            dist=self,
                            count=len(overrides),
                            overrides=pluralize(overrides, "override"),
                            requirements="\n".join(
                                "{index}. {override!r}".format(index=index, override=str(override))
                                for index, override in enumerate(overrides, start=1)
                            ),
                        )
                    )
                    modified_requires.extend(
                        Requirement.parse(str(override)) for override in overrides
                    )
                else:
                    modified_requires.append(req)
            return modified_requires

        return requires

    def patch_requires_dists(dist_type, requires_dists_function_name):
        target = getattr(dist_type, requires_dists_function_name)
        patched = create_requires(target)
        setattr(dist_type, requires_dists_function_name, patched)

    try:
        from pip._vendor.pkg_resources import Distribution

        patch_requires_dists(Distribution, "requires")
    except ImportError:
        pass

    # At some point in the Pip 21 series, distribution metadata migrated out of direct access from
    # `pkg_resources.Distribution` objects to a `pip._internal.metadata` interface. The
    # `pip._internal.metadata.pkg_resources.Distribution` type delegates to
    # `pip._vendor.pkg_resources.Distribution`, which we've patched above, but the
    # `pip._internal.metadata.importlib.Distribution` type needs its own patching. N.B.: Pip only
    # uses the pip._internal.metadata.importlib package for Python >=3.11 and code in that package
    # relies on that fact, using some syntax not supported in earlier Python versions; so we guard
    # this patch. See discussion here: https://github.com/pypa/pip/pull/11685/files#r1929802395
    if sys.version_info[:2] >= (3, 11):
        try:
            from pip._internal.metadata.importlib import Distribution

            patch_requires_dists(Distribution, "iter_dependencies")
        except ImportError:
            pass
