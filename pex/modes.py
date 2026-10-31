# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import stat

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Optional, Set, Text


class Modes(object):
    @classmethod
    def parse_value(cls, value):
        # type: (Text) -> Optional[Modes]

        if value == "original":
            return None

        def parse_octal(val):
            # type: (Text) -> int
            try:
                return int(val, 8)
            except ValueError as e:
                raise ValueError(
                    "Invalid modes value `{value}`: {err}\n"
                    "Must be bare octal mode digits of the mode to apply to all zip entries, e.g.: "
                    "`755`.".format(value=val, err=e)
                )

        modes = value.split(",")
        if len(modes) == 1:
            mode = parse_octal(modes[0])
            return Modes(directory=mode, executable=mode, file=mode)
        elif len(modes) == 3:
            missing = {"dir", "exe", "file"}  # type: Set[Text]
            values = {}
            for index, pair in enumerate(modes, start=1):
                file_type, _, value = pair.partition("=")
                if not value:
                    raise ValueError(
                        "Invalid mode setting value at position {index}: {value}\n"
                        "Mode settings must be of the form <file_type>=<mode> where <file_type> is "
                        "`dir`, `exe` or `file` and <mode> is the mode in octal digits, e.g: 755 "
                        "for rwx.".format(index=index, value=value)
                    )
                if file_type not in {"dir", "exe", "file"}:
                    raise ValueError(
                        "Invalid file type {file_type} for mode setting.\n"
                        "Must be one of `dir`, `exe` or `file`.".format(file_type=file_type)
                    )
                missing.discard(file_type)
                values[file_type] = parse_octal(value)
            if missing:
                raise ValueError(
                    "Missing mode settings for: {missing}\n"
                    "Must supply a setting for dir`, `exe` and `file`.".format(
                        missing=" and ".join(sorted(missing))
                    )
                )
            return Modes(directory=values["dir"], executable=values["exe"], file=values["file"])
        raise ValueError(
            "Invalid mode value: {value}\n"
            "The modes value must be either a single octal mode value to apply to all zip "
            "entries or else individual mode values keyed by file type of the form "
            "`dir=<mode>,exe=<mode>,file=<mode>`.".format(value=value)
        )

    @classmethod
    def render_value(cls, modes):
        # type: (Optional[Modes]) -> str
        return "original" if modes is None else str(modes)

    def __init__(
        self,
        directory=0o755,  # type: int
        executable=0o755,  # type: int
        file=0o644,  # type: int
    ):
        self.directory = stat.S_IFDIR | (directory & 0o777)
        self.executable = stat.S_IFREG | (executable & 0o777)
        self.file = stat.S_IFREG | (file & 0o777)

    def __str__(self):
        # type: () -> str

        if self.directory == self.executable == self.file:
            return "{:o}".format(self.directory)

        return "dir={dir:o},exe={exe:o},file={file:o}".format(
            dir=self.directory, exe=self.executable, file=self.file
        )

    def __eq__(self, value):
        # type: (Any) -> bool
        if type(self) != type(value):
            return NotImplemented
        return (self.directory, self.executable, self.file) == (
            value.directory,
            value.executable,
            value.file,
        )

    def __ne__(self, other):
        # type: (Any) -> bool
        return not self == other

    def hash(self):
        # type: () -> int
        return hash((self.directory, self.executable, self.file))
