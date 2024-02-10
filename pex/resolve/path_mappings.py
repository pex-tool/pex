# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def _normalize_path(path):
    # type: (str) -> str
    return os.path.normpath(path)


@attr.s(frozen=True)
class PathMapping(object):
    path = attr.ib(converter=_normalize_path)  # type: str
    name = attr.ib()  # type: str
    description = attr.ib(default=None)  # type: Optional[str]

    @path.validator
    def _validate_path(
        self,
        _attribute,  # type: Any
        value,  # type: str
    ):
        # type: (...) -> None
        if not os.path.isabs(value):
            raise ValueError("Mapped paths must be absolute. Given: {path}".format(path=value))

    @property
    def substitution_symbol(self):
        # type: () -> str
        return "${{{name}}}".format(name=self.name)


@attr.s(frozen=True)
class PathMappings(object):
    mappings = attr.ib(default=())  # type: Tuple[PathMapping, ...]

    def maybe_canonicalize(self, maybe_path):
        # type: (str) -> str

        # Inputs will look like:
        # artifact urls: file://<path>
        # requirement strings:
        #   PEP-440: req @ file://<path>
        #       Pip: <path>
        #       Pip: file://<path>
        for mapping in self.mappings:
            maybe_canonicalized = re.sub(
                re.escape(mapping.path), mapping.substitution_symbol, maybe_path
            )
            if maybe_canonicalized != maybe_path:
                return maybe_canonicalized
        return maybe_path

    def maybe_reify(self, maybe_path):
        # type: (str) -> str
        for mapping in self.mappings:
            maybe_reified = re.sub(re.escape(mapping.substitution_symbol), mapping.path, maybe_path)
            if maybe_reified != maybe_path:
                return maybe_reified
        return maybe_path
