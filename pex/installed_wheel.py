# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import json
import os

from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper
from pex.wheel import WHEEL, Wheel, WheelMetadataLoadError

if TYPE_CHECKING:
    from typing import Iterator, Optional, Text, Tuple

    import attr  # vendor:skip
else:
    import pex.third_party.attr as attr


@attr.s(frozen=True)
class InstalledWheel(object):
    class LoadError(Exception):
        """Indicates an installed wheel was not loadable at a particular path."""

    _LAYOUT_JSON_FILENAME = ".layout.json"

    @classmethod
    def layout_file(cls, prefix_dir):
        # type: (str) -> str
        return os.path.join(prefix_dir, cls._LAYOUT_JSON_FILENAME)

    @classmethod
    def save(
        cls,
        prefix_dir,  # type: str
        stash_dir,  # type: str
        record_relpath,  # type: Text
        root_is_purelib,  # type: bool
        sys_path_entries,  # type: Tuple[str, ...]
    ):
        # type: (...) -> InstalledWheel

        # We currently need the installed wheel chroot hash for PEX-INFO / boot purposes. It is
        # expensive to calculate; so we do it here 1 time when saving the installed wheel.
        fingerprint = CacheHelper.dir_hash(prefix_dir, hasher=hashlib.sha256)

        layout = {
            "stash_dir": stash_dir,
            "record_relpath": record_relpath,
            "fingerprint": fingerprint,
            "root_is_purelib": root_is_purelib,
            "sys_path_entries": sys_path_entries,
        }
        with open(cls.layout_file(prefix_dir), "w") as fp:
            json.dump(layout, fp, sort_keys=True, separators=(",", ":"))
        return cls(
            prefix_dir=prefix_dir,
            stash_dir=stash_dir,
            record_relpath=record_relpath,
            fingerprint=fingerprint,
            root_is_purelib=root_is_purelib,
            sys_path_entries=sys_path_entries,
        )

    @classmethod
    def load(cls, prefix_dir):
        # type: (str) -> InstalledWheel
        layout_file = cls.layout_file(prefix_dir)
        try:
            with open(layout_file) as fp:
                layout = json.load(fp)
        except (IOError, OSError) as e:
            raise cls.LoadError(
                "Failed to load an installed wheel layout from {layout_file}: {err}".format(
                    layout_file=layout_file, err=e
                )
            )
        if not isinstance(layout, dict):
            raise cls.LoadError(
                "The installed wheel layout file at {layout_file} must contain a single top-level "
                "object, found: {value}.".format(layout_file=layout_file, value=layout)
            )
        stash_dir = layout.get("stash_dir")
        record_relpath = layout.get("record_relpath")
        if not stash_dir or not record_relpath:
            raise cls.LoadError(
                "The installed wheel layout file at {layout_file} must contain an object with both "
                "`stash_dir` and `record_relpath` attributes, found: {value}".format(
                    layout_file=layout_file, value=layout
                )
            )

        fingerprint = layout.get("fingerprint")

        # N.B.: Caching root_is_purelib was not part of the original InstalledWheel layout data; so
        # we materialize the property if needed to support older installed wheel chroots.
        root_is_purelib = layout.get("root_is_purelib")
        if root_is_purelib is None:
            try:
                wheel = WHEEL.load(prefix_dir)
            except WheelMetadataLoadError as e:
                raise cls.LoadError(
                    "Failed to determine if installed wheel at {location} is platform-specific: "
                    "{err}".format(location=prefix_dir, err=e)
                )
            root_is_purelib = wheel.root_is_purelib

        # N.B.: Older versions of Pex installed wheel chroots did not have this field since the
        # `sys.path` entry was always just the prefix_dir for those.
        sys_path_entries = layout.get("sys_path_entries", [""])

        return cls(
            prefix_dir=prefix_dir,
            stash_dir=cast(str, stash_dir),
            record_relpath=cast(str, record_relpath),
            fingerprint=cast("Optional[str]", fingerprint),
            root_is_purelib=root_is_purelib,
            sys_path_entries=tuple(sys_path_entries),
        )

    prefix_dir = attr.ib()  # type: str
    stash_dir = attr.ib()  # type: str
    record_relpath = attr.ib()  # type: Text
    fingerprint = attr.ib()  # type: Optional[str]
    root_is_purelib = attr.ib()  # type: bool
    sys_path_entries = attr.ib()  # type: Tuple[str, ...]

    def wheel_file_name(self):
        # type: () -> str
        return Wheel.load(self.prefix_dir).wheel_file_name

    def stashed_path(self, *components):
        # type: (*str) -> str
        return os.path.join(self.prefix_dir, self.stash_dir, *components)

    def iter_sys_path_entries(self):
        # type: () -> Iterator[str]
        for sys_path_entry in self.sys_path_entries:
            yield os.path.normpath(os.path.join(self.prefix_dir, sys_path_entry))
