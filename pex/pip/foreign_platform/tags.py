# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import json
import os


def patch():
    from pip._internal.utils import compatibility_tags  # type: ignore[import]
    from pip._vendor.packaging import tags  # type: ignore[import]

    # N.B.: The following environment variable is used by the Pex runtime to control Pip and must be
    # kept in-sync with `__init__.py`.
    patched_tags_file = os.environ.pop("_PEX_PATCHED_TAGS_FILE")
    with open(patched_tags_file) as fp:
        patched_tags = tuple(
            itertools.chain.from_iterable(tags.parse_tag(tag) for tag in json.load(fp))
        )

    def get_supported(*_args, **_kwargs):
        return list(patched_tags)

    compatibility_tags.get_supported = get_supported
