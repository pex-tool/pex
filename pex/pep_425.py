# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools

from pex.orderedset import OrderedSet
from pex.third_party.packaging.tags import Tag, parse_tag
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Iterator, List, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def _prepare_tags(tags):
    # type: (Iterable[Tag]) -> Tuple[Tag, ...]
    return tags if isinstance(tags, tuple) else tuple(OrderedSet(tags))


@attr.s(frozen=True)
class CompatibilityTags(object):
    """An ordered set of PEP-425 compatibility tags.

    See: https://www.python.org/dev/peps/pep-0425/#use
    """

    @classmethod
    def from_strings(cls, tags):
        # type: (Iterable[str]) -> CompatibilityTags
        return cls(tags=itertools.chain.from_iterable(parse_tag(tag) for tag in tags))

    _tags = attr.ib(converter=_prepare_tags)  # type: Tuple[Tag, ...]

    def compatible_tags(self, tags):
        # type: (Iterable[Tag]) -> OrderedSet[Tag]

        query = frozenset(tags)

        def iter_compatible():
            for tag in self:
                if tag in query:
                    yield tag

        return OrderedSet(iter_compatible())

    def to_string_list(self):
        # type: () -> List[str]
        return [str(tag) for tag in self._tags]

    def __iter__(self):
        # type: () -> Iterator[Tag]
        return iter(self._tags)

    def __reversed__(self):
        return CompatibilityTags(tags=reversed(self._tags))

    def __getitem__(self, index):
        # type: (int) -> Tag
        return self._tags[index]
