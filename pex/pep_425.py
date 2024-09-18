# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import os.path

from pex.dist_metadata import is_wheel
from pex.orderedset import OrderedSet
from pex.rank import Rank
from pex.third_party.packaging.tags import Tag, parse_tag
from pex.typing import TYPE_CHECKING, cast, overload

if TYPE_CHECKING:
    from typing import Iterable, Iterator, List, Mapping, MutableMapping, Optional, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def _prepare_tags(tags):
    # type: (Iterable[Tag]) -> Tuple[Tag, ...]
    return tags if isinstance(tags, tuple) else tuple(OrderedSet(tags))


class TagRank(Rank["TagRank"]):
    """A Rank new-type to single out the ranking scheme for tags from other ranking schemes.

    The highest rank tag is the most specific tag.
    """


@attr.s(frozen=True)
class RankedTag(object):
    tag = attr.ib(order=False)  # type: Tag
    rank = attr.ib()  # type: TagRank

    def select_higher_rank(self, other):
        # type: (RankedTag) -> RankedTag
        return Rank.select_highest_rank(
            self, other, extract_rank=lambda ranked_tag: ranked_tag.rank
        )


@attr.s(frozen=True)
class CompatibilityTags(object):
    """A ranked set of PEP-425 compatibility tags.

    Tags are ordered most specific 1st to most generic last. The more specific a tag, the lower its
    rank value, with the most specific tag (best match) being ranked 0.

    See: https://www.python.org/dev/peps/pep-0425/#use
    """

    @classmethod
    def from_wheel(cls, wheel):
        # type: (str) -> CompatibilityTags
        if not is_wheel(wheel):
            raise ValueError(
                "Can only calculate wheel tags from a filename that ends in .whl per "
                "https://peps.python.org/pep-0427/#file-name-convention, given: {wheel!r}".format(
                    wheel=wheel
                )
            )
        wheel_stem, _ = os.path.splitext(os.path.basename(wheel))
        # Wheel filename format: https://www.python.org/dev/peps/pep-0427/#file-name-convention
        # `{distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl`
        wheel_components = wheel_stem.rsplit("-", 3)
        if len(wheel_components) != 4:
            pattern = "`-{python tag}-{abi tag}-{platform tag}.whl`"
            raise ValueError(
                "Can only calculate wheel tags from a filename that ends in {pattern} per "
                "https://peps.python.org/pep-0427/#file-name-convention, given: {wheel!r}".format(
                    pattern=pattern, wheel=wheel
                )
            )
        return cls(tags=tuple(parse_tag("-".join(wheel_components[-3:]))))

    @classmethod
    def from_strings(cls, tags):
        # type: (Iterable[str]) -> CompatibilityTags
        return cls(tags=tuple(itertools.chain.from_iterable(parse_tag(tag) for tag in tags)))

    _tags = attr.ib(converter=_prepare_tags)  # type: Tuple[Tag, ...]
    _rankings = attr.ib(eq=False, factory=dict)  # type: MutableMapping[Tag, TagRank]

    @_tags.validator
    def _validate_tags(
        self,
        attribute,  # type: attr.Attribute
        value,  # type: Tuple[Tag, ...]
    ):
        if not value:
            raise ValueError(
                "The {name} parameter should contain at least one tag; given an empty set.".format(
                    name=attribute.name
                )
            )

    def extend(self, tags):
        # type: (Iterable[Tag]) -> CompatibilityTags
        return CompatibilityTags(self._tags + tuple(tags))

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

    @property
    def __rankings(self):
        # type: () -> Mapping[Tag, TagRank]
        if not self._rankings:
            self._rankings.update(TagRank.ranked(self._tags))
        return self._rankings

    @property
    def lowest_rank(self):
        # type: () -> TagRank
        return cast(TagRank, self.rank(self[-1]))

    def rank(self, tag):
        # type: (Tag) -> Optional[TagRank]
        return self.__rankings.get(tag)

    def best_match(self, tags):
        # type: (Iterable[Tag]) -> Optional[RankedTag]
        best_match = None  # type: Optional[RankedTag]
        for tag in tags:
            rank = self.rank(tag)
            if rank is None:
                continue
            ranked_tag = RankedTag(tag=tag, rank=rank)
            if best_match is None or ranked_tag is best_match.select_higher_rank(ranked_tag):
                best_match = ranked_tag
        return best_match

    def __iter__(self):
        # type: () -> Iterator[Tag]
        return iter(self._tags)

    def __len__(self):
        # type: () -> int
        return len(self._tags)

    @overload
    def __getitem__(self, index):
        # type: (int) -> Tag
        pass

    # MyPy claims this overload collides with the one below even though slice / Tag are disjoint
    # input types and CompatibilityTags / TagRank are disjoint return types; thus the ignore[misc].
    @overload
    def __getitem__(self, slice_):  # type: ignore[misc]
        # type: (slice) -> CompatibilityTags
        pass

    @overload
    def __getitem__(self, tag):
        # type: (Tag) -> TagRank
        pass

    def __getitem__(self, index_or_slice_or_tag):
        # type: (Union[int, slice, Tag]) -> Union[Tag, CompatibilityTags, TagRank]
        """Retrieve tag by its rank or a tags rank.

        Ranks are 0-based with the 0-rank tag being the most specific (best match).
        """
        if isinstance(index_or_slice_or_tag, Tag):
            return self.__rankings[index_or_slice_or_tag]
        elif isinstance(index_or_slice_or_tag, slice):
            tags = self._tags[index_or_slice_or_tag]
            return CompatibilityTags(
                tags=tags, rankings={tag: self.__rankings[tag] for tag in tags}
            )
        else:
            return self._tags[index_or_slice_or_tag]
