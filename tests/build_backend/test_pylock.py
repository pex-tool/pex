# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re

import pytest

from pex.build_backend.configuration import ConfigurationError
from pex.build_backend.pylock import ScriptLock, ScriptLocks
from pex.common import touch
from testing.pytest_utils.tmp import Tempdir


def test_none():
    # type: () -> None

    assert ScriptLocks.load("project_dir", []) is None


def test_duplicate(tmpdir):
    # type: (Tempdir) -> None

    project = tmpdir.join("project")
    for lock in "foo/pylock.toml", "bar/pylock.toml", "spam1.lock", "foo1.lock", "foo2.lock":
        touch(os.path.join(project, lock))

    with pytest.raises(
        ConfigurationError,
        match=re.escape(
            "The following lock has more than one entry; lock names must be unique:\n" "pylock.toml"
        ),
    ):
        ScriptLocks.load(
            project_directory=project,
            config=[{"path": "foo/pylock.toml"}, {"path": "bar/pylock.toml"}],
        )

    with pytest.raises(
        ConfigurationError,
        match=re.escape(
            "The following locks have more than one entry; lock names must be unique:\n"
            "pylock.toml\n"
            "pylock.foo.toml"
        ),
    ):
        ScriptLocks.load(
            project_directory=project,
            config=[
                {"path": "foo/pylock.toml"},
                {"name": "spam", "path": "spam1.lock"},
                {"path": "bar/pylock.toml"},
                {"name": "foo", "path": "foo1.lock"},
                {"name": "foo", "path": "foo2.lock"},
            ],
        )


def test_path_and_command(tmpdir):
    # type: (Tempdir) -> None

    project = tmpdir.join("project")
    touch(os.path.join(project, "foo"))

    with pytest.raises(
        ConfigurationError,
        match=re.escape(
            "You can either specify a lock `path` or a lock generating `command` for "
            "[tool.pex.build_backend.script-locks][0], but not both."
        ),
    ):
        ScriptLocks.load(
            project_directory=project, config=[{"path": "foo", "command": ["ls", "-l"]}]
        )


def test_file_name():
    assert "pylock.toml" == ScriptLock.file_name()
    assert "pylock.toml" == ScriptLock.file_name("")
    assert "pylock.foo.toml" == ScriptLock.file_name("foo")
    assert "pylock.pylock.foo.toml.toml" == ScriptLock.file_name("pylock.foo.toml")


def test_lock_name():
    assert "" == ScriptLock.lock_name("pylock.toml")
    assert "foo" == ScriptLock.lock_name("pylock.foo.toml")
    assert ScriptLock.lock_name("foo") is None
