# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import os
import re
from email.message import Message

from pex.dist_metadata import (
    DistMetadata,
    Distribution,
    MetadataFiles,
    MetadataType,
    load_metadata,
    parse_message,
)
from pex.orderedset import OrderedSet
from pex.third_party.packaging import tags
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Dict, Optional, Text, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class WheelMetadataLoadError(ValueError):
    """Indicates an error loading WHEEL metadata."""


@attr.s(frozen=True)
class WHEEL(object):
    """The .whl WHEEL metadata file.

    See item 6 here for the WHEEL file contents: https://peps.python.org/pep-0427/#file-contents
    """

    @classmethod
    def _from_metadata_files(cls, metadata_files):
        # type: (MetadataFiles) -> WHEEL

        metadata_bytes = metadata_files.read("WHEEL")
        if not metadata_bytes:
            raise WheelMetadataLoadError(
                "Could not find WHEEL metadata in {wheel}.".format(
                    wheel=metadata_files.render_description(metadata_file_name="WHEEL")
                )
            )
        metadata = parse_message(metadata_bytes)
        return cls(files=metadata_files, metadata=metadata)

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
            wheel = cls._from_metadata_files(metadata_files)
            cls._CACHE[location] = wheel
        return wheel

    @classmethod
    def from_distribution(cls, distribution):
        # type: (Distribution) -> WHEEL
        location = distribution.metadata.files.metadata.path
        wheel = cls._CACHE.get(location)
        if not wheel:
            wheel = cls._from_metadata_files(distribution.metadata.files)
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
    @staticmethod
    def _source(
        location,  # type: str
        metadata_files,  # type: MetadataFiles
    ):
        # type: (...) -> str
        return "{project_name} {version} at {location}".format(
            project_name=metadata_files.metadata.project_name,
            version=metadata_files.metadata.version,
            location=location,
        )

    @classmethod
    def _from_metadata_files(
        cls,
        location,  # type: str
        metadata_files,  # type: MetadataFiles
        wheel=None,  # type: Optional[WHEEL]
    ):
        # type: (...) -> Wheel

        if wheel:
            metadata = wheel
        else:
            wheel_data = metadata_files.read("WHEEL")
            if not wheel_data:
                raise WheelMetadataLoadError(
                    "Could not find WHEEL metadata in {source}.".format(
                        source=cls._source(location, metadata_files)
                    )
                )
            metadata = WHEEL(files=metadata_files, metadata=parse_message(wheel_data))

        wheel_metadata_dir = os.path.dirname(metadata_files.metadata.rel_path)
        if not wheel_metadata_dir.endswith(".dist-info"):
            raise WheelMetadataLoadError(
                "Expected METADATA file for {source} to be housed in a .dist-info directory, but "
                "was found at {wheel_metadata_path}.".format(
                    source=cls._source(location, metadata_files),
                    wheel_metadata_path=metadata_files.metadata.rel_path,
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
            location=location,
            metadata_dir=metadata_dir,
            metadata_files=metadata_files,
            metadata=metadata,
            data_dir=data_dir,
        )

    @classmethod
    def load(cls, wheel_path):
        # type: (str) -> Wheel

        wheel = WHEEL.load(wheel_path)
        return cls._from_metadata_files(
            location=wheel_path, metadata_files=wheel.files, wheel=wheel
        )

    @classmethod
    def from_distribution(cls, distribution):
        # type: (Distribution) -> Wheel
        return cls._from_metadata_files(
            location=distribution.location, metadata_files=distribution.metadata.files
        )

    location = attr.ib()  # type: str
    metadata_dir = attr.ib()  # type: str
    metadata_files = attr.ib()  # type: MetadataFiles
    metadata = attr.ib()  # type: WHEEL
    data_dir = attr.ib()  # type: str

    @property
    def source(self):
        # type: () -> str
        return self._source(self.location, self.metadata_files)

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
        # type: () -> DistMetadata
        return DistMetadata.from_metadata_files(self.metadata_files)

    def metadata_path(self, *components):
        # type: (*str) -> str
        return os.path.join(self.metadata_dir, *components)

    def data_path(self, *components):
        # type: (*str) -> str
        return os.path.join(self.data_dir, *components)
