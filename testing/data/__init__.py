# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import pkgutil


def load(rel_path):
    # type: (str) -> bytes
    data = pkgutil.get_data(__name__, rel_path)
    if data is None:
        raise ValueError(
            "No resource found at {rel_path} from package {name}.".format(
                rel_path=rel_path, name=__name__
            )
        )
    return data


def path(*rel_path):
    # type: (*str) -> str
    path = os.path.join(os.path.dirname(__file__), *rel_path)
    if not os.path.isfile(path):
        raise ValueError("No resource found at {path}.".format(path=path))
    return path
