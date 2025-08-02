# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def qualified_name(item):
    # type: (Any) -> str
    """Attempt to produce the fully qualified name for an item.

    If the item is a type, method, property or function, its fully qualified name is returned as
    best as can be determined. Otherwise, the fully qualified name of the type of the given item is
    returned.

    :param item: The item to identify.
    :return: The fully qualified name of the given item.
    """
    if isinstance(item, property):
        item = item.fget
    if not hasattr(item, "__name__"):
        item = type(item)
    return "{module}.{type}".format(
        module=getattr(item, "__module__", "<unknown module>"),
        # There is no __qualname__ in Python 2.7; so we do the best we can.
        type=getattr(item, "__qualname__", item.__name__),
    )
