# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Optional, Tuple


"""Commonly needed attr.ib converters."""


def str_tuple_from_iterable(iterable=None):
    # type: (Optional[Iterable[str]]) -> Tuple[str, ...]
    return tuple(iterable) if iterable is not None else ()
