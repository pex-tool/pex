# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

# N.B.: The following environment variables are used by the Pex runtime to control Pip and must be
# kept in-sync with `foreign_platform.py`.
patched_markers_file = os.environ.pop("_PEX_PATCHED_MARKERS_FILE", None)
patched_tags_file = os.environ.pop("_PEX_PATCHED_TAGS_FILE", None)

if patched_markers_file:

    def patch_markers_default_environment():
        import json

        from pip._vendor.packaging import markers  # type: ignore[import]

        with open(patched_markers_file) as fp:
            patched_markers = json.load(fp)

        markers.default_environment = patched_markers.copy

    patch_markers_default_environment()
    del patch_markers_default_environment


if patched_tags_file:

    def patch_compatibility_tags():
        import itertools
        import json

        from pip._internal.utils import compatibility_tags  # type: ignore[import]
        from pip._vendor.packaging import tags  # type: ignore[import]

        with open(patched_tags_file) as fp:
            tags = tuple(
                itertools.chain.from_iterable(tags.parse_tag(tag) for tag in json.load(fp))
            )

        def get_supported(*args, **kwargs):
            return list(tags)

        compatibility_tags.get_supported = get_supported

    patch_compatibility_tags()
    del patch_compatibility_tags
