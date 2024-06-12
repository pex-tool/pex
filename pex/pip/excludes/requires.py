# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import logging

logger = logging.getLogger(__name__)


def patch():
    from pex.dist_metadata import Requirement
    from pex.pip.excludes import PatchContext

    exclude_configuration = PatchContext.load_exclude_configuration()

    def create_requires(orig_requires):
        def requires(self, *args, **kwargs):
            unexcluded_requires = []
            for req in orig_requires(self, *args, **kwargs):
                excluded_by = exclude_configuration.excluded_by(Requirement.parse(str(req)))
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
                unexcluded_requires.append(req)
            return unexcluded_requires

        return requires

    def patch_requires_dists(dist_type, requires_dists_function_name):
        target = getattr(dist_type, requires_dists_function_name)
        patched = create_requires(target)
        setattr(dist_type, requires_dists_function_name, patched)

    try:
        from pip._vendor.pkg_resources import Distribution  # type: ignore[import]

        patch_requires_dists(Distribution, "requires")
    except ImportError:
        pass

    # At some point in the Pip 21 series, distribution metadata migrated out of direct access from
    # `pkg_resources.Distribution` objects to a `pip._internal.metadata` interface. The
    # `pip._internal.metadata.pkg_resources.Distribution` type delegates to
    # `pip._vendor.pkg_resources.Distribution`, which we've patched above, but the
    # `pip._internal.metadata.importlib.Distribution` type needs its own patching.
    try:
        from pip._internal.metadata.importlib import Distribution  # type: ignore[import]

        patch_requires_dists(Distribution, "iter_dependencies")
    except ImportError:
        pass
