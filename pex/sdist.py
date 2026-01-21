# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import copy
import os.path
import sys
import tarfile
from tarfile import TarInfo

from pex.compatibility import commonpath
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Dict, Optional, Text, TypeVar


class FilterError(tarfile.TarError):
    pass


class AbsolutePathError(FilterError):
    pass


class OutsideDestinationError(FilterError):
    pass


class SpecialFileError(FilterError):
    pass


class AbsoluteLinkError(FilterError):
    pass


class LinkOutsideDestinationError(FilterError):
    pass


_REALPATH_KWARGS = (
    {"strict": getattr(os.path, "ALLOW_MISSING", False)} if sys.version_info[:2] >= (3, 10) else {}
)  # type: Dict[str, Any]


if TYPE_CHECKING:
    _Text = TypeVar("_Text", str, Text)


def _realpath(path):
    # type: (_Text) -> _Text
    return os.path.realpath(path, **_REALPATH_KWARGS)


def _get_filtered_attrs(
    member,  # type: TarInfo
    dest_path,  # type: Text
    for_data=True,  # type: bool
):
    # type: (...) -> Dict[str, Any]

    # N.B.: Copied from CPython 3.14 stdlib tarfile.py
    # Modifications:
    # + Exception types replicated with error messages placed at call site.
    # + `os.path.realpath` -> `_realpath` to deal with `strict` parameter.
    # + `os.path.commonpath` -> `pex.compatibility.commonpath`
    # + `mode = None` guarded by `sys.version_info[:2] >= (3, 12)` with commentary.
    # + `{uid,gid,uname,gname} = None` guarded by `sys.version_info[:2] >= (3, 12)` with commentary.

    new_attrs = {}  # type: Dict[str, Any]
    name = member.name
    dest_path = _realpath(dest_path)
    # Strip leading / (tar's directory separator) from filenames.
    # Include os.sep (target OS directory separator) as well.
    if name.startswith(("/", os.sep)):
        name = new_attrs["name"] = member.path.lstrip("/" + os.sep)
    if os.path.isabs(name):
        # Path is absolute even after stripping.
        # For example, 'C:/foo' on Windows.
        raise AbsolutePathError("member {name!r} has an absolute path".format(name=member.name))
    # Ensure we stay in the destination
    target_path = _realpath(os.path.join(dest_path, name))
    if commonpath([target_path, dest_path]) != dest_path:
        raise OutsideDestinationError(
            "{name!r} would be extracted to {path!r}, which is outside the destination".format(
                name=member.name, path=target_path
            )
        )
    # Limit permissions (no high bits, and go-w)
    mode = member.mode  # type: Optional[int]
    if mode is not None:
        # Strip high bits & group/other write bits
        mode = mode & 0o755
        if for_data:
            # For data, handle permissions & file types
            if member.isreg() or member.islnk():
                if not mode & 0o100:
                    # Clear executable bits if not executable by user
                    mode &= ~0o111
                # Ensure owner can read & write
                mode |= 0o600
            elif member.isdir() or member.issym():
                if sys.version_info[:2] >= (3, 12):
                    # Ignore mode for directories & symlinks
                    mode = None
                else:
                    # Retain stripped mode since older Pythons do not support None.
                    pass
            else:
                # Reject special files
                raise SpecialFileError("{name!r} is a special file".format(name=member.name))
        if mode != member.mode:
            new_attrs["mode"] = mode
    if for_data:
        if sys.version_info[:2] >= (3, 12):
            # Ignore ownership for 'data'
            if member.uid is not None:
                new_attrs["uid"] = None
            if member.gid is not None:
                new_attrs["gid"] = None
            if member.uname is not None:
                new_attrs["uname"] = None
            if member.gname is not None:
                new_attrs["gname"] = None
        else:
            # Retain uid/gid/uname/gname since older Pythons do not support None.
            pass

        # Check link destination for 'data'
        if member.islnk() or member.issym():
            if os.path.isabs(member.linkname):
                raise AbsoluteLinkError(
                    "{name!r} is a link to an absolute path".format(name=member.name)
                )
            normalized = os.path.normpath(member.linkname)
            if normalized != member.linkname:
                new_attrs["linkname"] = normalized
            if member.issym():
                target_path = os.path.join(dest_path, os.path.dirname(name), member.linkname)
            else:
                target_path = os.path.join(dest_path, member.linkname)
            target_path = _realpath(target_path)
            if commonpath([target_path, dest_path]) != dest_path:
                raise LinkOutsideDestinationError(
                    "{name!r} would link to {path!r}, which is outside the destination".format(
                        name=member.name, path=target_path
                    )
                )
    return new_attrs


def _replace(
    member,  # type: TarInfo
    attrs,  # type: Dict[str, Any]
):
    # type: (...) -> TarInfo

    replace = getattr(member, "replace", None)
    if replace:
        attrs["deep"] = False
        return cast(TarInfo, replace(**attrs))

    result = copy.copy(member)
    for attr, value in attrs.items():
        setattr(result, attr, value)
    return result


def _data_filter(
    member,  # type: TarInfo
    dest_path,  # type: Text
):
    # type: (...) -> TarInfo
    new_attrs = _get_filtered_attrs(member, dest_path, True)
    if new_attrs:
        return _replace(member, new_attrs)
    return member


_EXTRACTALL_DATA_FILTER_KWARGS = {"filter": "data"}  # type: Dict[str, Any]


class InvalidSourceDistributionError(ValueError):
    pass


def extract_tarball(
    tarball_path,  # type: Text
    dest_dir,  # type: _Text
):
    # type: (...) -> _Text

    with tarfile.open(tarball_path) as tf:
        if sys.version_info[:2] >= (3, 12):
            tf.extractall(dest_dir, **_EXTRACTALL_DATA_FILTER_KWARGS)
        else:
            for tar_info in tf:  # type: ignore[unreachable]
                tar_info = _data_filter(tar_info, dest_dir)
                tf.extract(tar_info, dest_dir)

    listing = os.listdir(dest_dir)
    if len(listing) != 1:
        raise InvalidSourceDistributionError(
            "Expected one top-level project directory to be extracted from {project}, "
            "found {count}: {listing}".format(
                project=tarball_path, count=len(listing), listing=", ".join(listing)
            )
        )

    project_dir = os.path.join(dest_dir, listing[0])
    if not os.path.isdir(project_dir):
        raise InvalidSourceDistributionError(
            "Expected one top-level project directory to be extracted from {project}, "
            "found file: {path}".format(project=tarball_path, path=listing[0])
        )

    return project_dir
