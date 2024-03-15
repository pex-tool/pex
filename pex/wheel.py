# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from email.message import Message

from pex.dist_metadata import MetadataFiles, MetadataType, load_metadata, parse_message
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Dict, Text

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class WHEEL(object):
    """The .whl WHEEL metadata file.

    See item 6 here for the WHEEL file contents: https://peps.python.org/pep-0427/#file-contents
    """

    class LoadError(Exception):
        """Indicates an error loading WHEEL metadata."""

    _CACHE = {}  # type: Dict[Text, WHEEL]

    @classmethod
    def load(cls, location):
        # type: (Text) -> WHEEL
        wheel = cls._CACHE.get(location)
        if not wheel:
            metadata_files = load_metadata(location, restrict_types_to=(MetadataType.DIST_INFO,))
            if not metadata_files:
                raise cls.LoadError(
                    "Could not find any metadata in {wheel}.".format(wheel=location)
                )

            metadata_bytes = metadata_files.read("WHEEL")
            if not metadata_bytes:
                raise cls.LoadError(
                    "Could not find WHEEL metadata in {wheel}.".format(wheel=location)
                )
            metadata = parse_message(metadata_bytes)
            wheel = cls(files=metadata_files, metadata=metadata)
            cls._CACHE[location] = wheel
        return wheel

    files = attr.ib()  # type: MetadataFiles
    metadata = attr.ib()  # type: Message

    @property
    def root_is_purelib(self):
        # type: () -> bool

        # See:
        #   https://peps.python.org/pep-0427/#installing-a-wheel-distribution-1-0-py32-none-any-whl
        return cast(bool, "true" == self.metadata.get("Root-Is-Purelib"))
