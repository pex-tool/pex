# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import re
import sys
from collections import OrderedDict
from datetime import date, datetime, time
from io import BytesIO

from pex.compatibility import string
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import IO, Any, Dict, List, Text, Tuple, Union

TOMLI_SUPPORTED = sys.version_info[:2] >= (3, 7)


if not TOMLI_SUPPORTED:
    from pex.third_party.toml import TomlDecodeError as _TomlDecodeError
    from pex.third_party.toml import load as _load
    from pex.third_party.toml import loads as _loads

    def load(source):
        # type: (Union[str, IO[bytes]]) -> Dict[str, Any]
        if isinstance(source, str):
            return cast("Dict[str, Any]", _load(source))
        else:
            return cast("Dict[str, Any]", _loads(source.read().decode("utf-8")))

else:
    from pex.third_party.tomli import TOMLDecodeError as _TomlDecodeError
    from pex.third_party.tomli import load as _load
    from pex.third_party.tomli import loads as _loads

    def load(source):
        # type: (Union[str, IO[bytes]]) -> Dict[str, Any]
        if isinstance(source, str):
            with open(source, "rb") as fp:
                return cast("Dict[str, Any]", _load(fp))
        else:
            return cast("Dict[str, Any]", _load(source))


loads = _loads
TomlDecodeError = _TomlDecodeError


class InlineTable(OrderedDict):
    @classmethod
    def create(cls, *items):
        # type: (*Tuple[str, Any]) -> InlineTable
        return InlineTable(items)


class InlineArray(list):
    pass


_INLINE_TYPES = (
    InlineArray,
    InlineTable,
    bool,
    date,
    datetime,
    float,
    int,
    time,
) + string


# See: https://toml.io/en/v1.0.0#spec
_ENCODING = "utf-8"


# See: https://toml.io/en/v1.0.0#string
_STRING_ESCAPES = {
    "\b": r"\b",
    "\t": r"\t",
    "\n": r"\n",
    "\f": r"\f",
    "\r": r"\r",
    '"': r"\"",
    "\\": r"\\",
}  # type: Dict[Text, Text]


def _escape_string(value):
    # type: (Any) -> Text
    return "".join(_STRING_ESCAPES.get(char, str(char)) for char in value)


# See: https://toml.io/en/v1.0.0#keys
def _safe_key(key):
    # type: (str) -> str
    if re.match(r"^[A-Za-z0-9_-]+$", key):
        return key
    return '"{key}"'.format(key=_escape_string(key))


class UnexpectedValueError(ValueError):
    @classmethod
    def create(cls, value):
        # type: (Any) -> UnexpectedValueError
        return cls(
            "Got an unexpected value while converting a Pex lock file to pylock.toml format:\n"
            "{value} of type {type}\n"
            "Can only handle values of type {inline_types}, list (or tuple) and dict.".format(
                value=value,
                type=type(value),
                inline_types=", ".join(typ.__name__ for typ in _INLINE_TYPES),
            )
        )


def _dump(
    data,  # type: Union[Dict, InlineArray, InlineTable, List, Text, Tuple, bool, date, datetime, float, int, time]
    output,  # type: IO[bytes]
    path="",  # type: str
    indent=b"",  # type: bytes
):
    if isinstance(data, InlineArray):
        if not all(isinstance(item, _INLINE_TYPES) for item in data):
            raise ValueError(
                "Got an unexpected value while converting a Pex lock file to pylock.toml format:\n"
                "Found a {count} item inline list at {path} with at least one non-inlinable "
                "item.\n".format(count=len(data), path=path)
            )
        output.write(b"[")
        for index, item in enumerate(data):
            if index > 0:
                output.write(b", ")
            _dump(item, output)
        output.write(b"]")
        return

    if isinstance(data, InlineTable):
        if not all(isinstance(item, _INLINE_TYPES) for item in data.values()):
            raise ValueError(
                "Got an unexpected value while converting a Pex lock file to pylock.toml format:\n"
                "Found a {count} item inline table at {path} with at least one non-inlinable "
                "item.\n".format(count=len(data), path=path)
            )
        output.write(b"{")
        for index, (key, value) in enumerate(data.items()):
            if index > 0:
                output.write(b", ")
            output.write("{key} = ".format(key=_safe_key(key)).encode(_ENCODING))
            _dump(value, output)
        output.write(b"}")
        return

    if isinstance(data, bool):
        output.write(b"true" if data else b"false")
        return

    if isinstance(data, (date, datetime, time)):
        output.write(data.isoformat().encode(_ENCODING))
        return

    if isinstance(data, (float, int)):
        output.write(str(data).encode(_ENCODING))
        return

    if isinstance(data, string):
        output.write('"{value}"'.format(value=_escape_string(data)).encode(_ENCODING))
        return

    if isinstance(data, (list, tuple)):
        output.write(indent)
        output.write(b"[")
        if data:
            list_indent = indent + (b" " * 4)
            for index, item in enumerate(data):
                output.write(b"\n")
                output.write(list_indent)
                if isinstance(item, dict):
                    item = InlineTable(item)
                elif isinstance(item, (list, tuple)):
                    item = InlineArray(item)
                _dump(item, output, indent=list_indent)
                output.write(b",")
            output.write(b"\n")
        output.write(indent)
        output.write(b"]")
        return

    if not isinstance(data, dict):
        raise UnexpectedValueError.create(data)

    def extend_path(sub_key):
        # type: (str) -> str
        sub_key = _safe_key(sub_key)
        return "{path}.{key}".format(path=path, key=sub_key) if path else sub_key

    new_tables = []  # type: List[Tuple[str, Any]]
    for key, value in data.items():
        main_table_output = isinstance(value, _INLINE_TYPES)
        main_table_output = main_table_output or (
            isinstance(value, (list, tuple))
            and (
                all(isinstance(item, _INLINE_TYPES) for item in value)
                or not all(isinstance(item, dict) for item in value)
            )
        )
        if not main_table_output:
            new_tables.append((key, value))
            continue

        output.write("{key} = ".format(key=_safe_key(key)).encode(_ENCODING))
        _dump(value, output)
        output.write(b"\n")

    for key, value in new_tables:
        if isinstance(value, dict):
            new_path = extend_path(key)
            if any(not isinstance(value, dict) for value in value.values()):
                output.write("\n[{path}]\n".format(path=new_path).encode(_ENCODING))
            _dump(value, output, path=new_path)
        elif isinstance(value, (list, tuple)):
            new_path = extend_path(key)
            for item in value:
                output.write("\n[[{path}]]\n".format(path=new_path).encode(_ENCODING))
                _dump(item, output, path=new_path)
        else:
            raise UnexpectedValueError.create(value)


def dump(
    data,  # type: Dict[str, Any]
    output,  # type: IO[bytes]
):
    _dump(data, output)


def dumps(data):
    # type: (Dict[str, Any]) -> Text
    result = BytesIO()
    dump(data, result)
    return result.getvalue().decode(_ENCODING)
