# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import os
import re
from email.message import Message

from pex.dist_metadata import (
    DistMetadata,
    MetadataFiles,
    MetadataType,
    load_metadata,
    parse_message,
)
from pex.orderedset import OrderedSet
from pex.third_party.packaging import tags
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Dict, Text, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class WheelMetadataLoadError(Exception):
    """Indicates an error loading WHEEL metadata."""


@attr.s(frozen=True)
class WHEEL(object):
    """The .whl WHEEL metadata file.

    See item 6 here for the WHEEL file contents: https://peps.python.org/pep-0427/#file-contents
    """

    _CACHE = {}  # type: Dict[Text, WHEEL]

    @classmethod
    def load(cls, location):
        # type: (Text) -> WHEEL
        wheel = cls._CACHE.get(location)
        if not wheel:
            metadata_files = load_metadata(location, restrict_types_to=(MetadataType.DIST_INFO,))
            if not metadata_files:
                raise WheelMetadataLoadError(
                    "Could not find any metadata in {wheel}.".format(wheel=location)
                )

            metadata_bytes = metadata_files.read("WHEEL")
            if not metadata_bytes:
                raise WheelMetadataLoadError(
                    "Could not find WHEEL metadata in {wheel}.".format(wheel=location)
                )
            metadata = parse_message(metadata_bytes)
            wheel = cls(files=metadata_files, metadata=metadata)
            cls._CACHE[location] = wheel
        return wheel

    files = attr.ib()  # type: MetadataFiles
    metadata = attr.ib()  # type: Message

    @property
    def tags(self):
        # type: () -> Tuple[tags.Tag, ...]
        return tuple(
            itertools.chain.from_iterable(
                tags.parse_tag(tag) for tag in self.metadata.get_all("Tag", ())
            )
        )

    @property
    def root_is_purelib(self):
        # type: () -> bool

        # See:
        #   https://peps.python.org/pep-0427/#installing-a-wheel-distribution-1-0-py32-none-any-whl
        return cast(bool, "true" == self.metadata.get("Root-Is-Purelib"))


@attr.s(frozen=True)
class Wheel(object):
    @classmethod
    def load(cls, wheel_path):
        # type: (str) -> Wheel

        metadata = WHEEL.load(wheel_path)

        metadata_path = metadata.files.metadata_file_rel_path("WHEEL")
        if not metadata_path:
            raise WheelMetadataLoadError(
                "Could not find WHEEL metadata in {wheel}.".format(wheel=wheel_path)
            )

        wheel_metadata_dir = os.path.dirname(metadata_path)
        if not wheel_metadata_dir.endswith(".dist-info"):
            raise WheelMetadataLoadError(
                "Expected WHEEL metadata for {wheel} to be housed in a .dist-info directory, but was "
                "found at {wheel_metadata_path}.".format(
                    wheel=wheel_path, wheel_metadata_path=metadata_path
                )
            )
        # Although not crisply defined, all PEPs lead to PEP-508 which restricts project names
        # to ASCII: https://peps.python.org/pep-0508/#names. Likewise, version numbers are also
        # restricted to ASCII: https://peps.python.org/pep-0440/. Since the `.dist-info` dir
        # path is defined as `<project name>-<version>.dist-info` in
        # https://peps.python.org/pep-0427/, we are safe in assuming ASCII overall for the wheel
        # metadata dir path.
        metadata_dir = str(wheel_metadata_dir)

        data_dir = re.sub(r"\.dist-info$", ".data", metadata_dir)

        return cls(
            location=wheel_path,
            metadata_dir=metadata_dir,
            metadata_files=metadata.files,
            metadata=metadata,
            data_dir=data_dir,
        )

    location = attr.ib()  # type: str
    metadata_dir = attr.ib()  # type: str
    metadata_files = attr.ib()  # type: MetadataFiles
    metadata = attr.ib()  # type: WHEEL
    data_dir = attr.ib()  # type: str

    @property
    def wheel_file_name(self):
        # type: () -> str

        interpreters = OrderedSet()  # type: OrderedSet[str]
        abis = OrderedSet()  # type: OrderedSet[str]
        platforms = OrderedSet()  # type: OrderedSet[str]
        for tag in self.metadata.tags:
            interpreters.add(tag.interpreter)
            abis.add(tag.abi)
            platforms.add(tag.platform)
        tag = "{interpreters}-{abis}-{platforms}".format(
            interpreters=".".join(interpreters), abis=".".join(abis), platforms=".".join(platforms)
        )

        return "{project_name}-{version}-{tag}.whl".format(
            project_name=self.metadata_files.metadata.project_name.raw,
            version=self.metadata_files.metadata.version.raw,
            tag=tag,
        )

    @property
    def root_is_purelib(self):
        # type: () -> bool
        return self.metadata.root_is_purelib

    def dist_metadata(self):
        return DistMetadata.from_metadata_files(self.metadata_files)

    def metadata_path(self, *components):
        # typ: (*str) -> str
        return os.path.join(self.metadata_dir, *components)

    def data_path(self, *components):
        # typ: (*str) -> str
        return os.path.join(self.data_dir, *components)
