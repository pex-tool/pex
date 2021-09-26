# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.cli.commands.lockfile.lockfile import Lockfile as Lockfile  # For re-export.
from pex.common import safe_open
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Text


class ParseError(Exception):
    """Indicates an error parsing a Pex lock file."""


def load(lockfile_path):
    # type: (str) -> Lockfile
    """Loads the Pex lock file stored at the given path.

    :param lockfile_path: The path to the Pex lock file to load.
    :return: The parsed lock file.
    :raises: :class:`ParseError` if there was a problem parsing the lock file.
    """
    from pex.cli.commands.lockfile import json_codec

    return json_codec.load(lockfile_path=lockfile_path)


def loads(
    lockfile_contents,  # type: Text
    source="<string>",  # type: str
):
    # type: (...) -> Lockfile
    """Parses the given Pex lock file contents.

    :param lockfile_contents: The contents of a Pex lock file.
    :param source: A descriptive name for the source of the lock file contents.
    :return: The parsed lock file.
    :raises: :class:`ParseError` if there was a problem parsing the lock file.
    """
    from pex.cli.commands.lockfile import json_codec

    return json_codec.loads(lockfile_contents=lockfile_contents, source=source)


def store(
    lockfile,  # type: Lockfile
    path,  # type: str
):
    # type: (...) -> None
    """Stores the given lock file at the given path.

    Any missing parent directories in the path will be created and any pre-existing file at the
    path wil be over-written.

    :param lockfile: The lock file to store.
    :param path: The path to store the lock file at.
    """
    import json
    from pex.cli.commands.lockfile import json_codec

    with safe_open(path, "w") as fp:
        json.dump(json_codec.as_json_data(lockfile), fp, sort_keys=True)
