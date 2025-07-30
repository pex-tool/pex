# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import functools
import itertools
import os.path
import subprocess
import sys
from collections import defaultdict
from subprocess import CalledProcessError
from typing import DefaultDict, List, Text

from pex.build_backend import BuildError
from pex.build_backend.configuration import ConfigurationError
from pex.common import pluralize, safe_copy, safe_mkdir
from pex.compatibility import string, text
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Dict, Optional, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Command(object):
    args = attr.ib()  # type: Tuple[Text, ...]


@attr.s(frozen=True)
class ScriptLock(object):
    @staticmethod
    def file_name(lock_name=""):
        # type: (str) -> str
        return "pylock.{name}.toml".format(name=lock_name) if lock_name else "pylock.toml"

    @staticmethod
    def lock_name(path):
        # type: (str) -> Optional[str]

        lock_name = os.path.basename(path)
        if lock_name == "pylock.toml":
            return ""
        if lock_name.startswith("pylock.") and lock_name.endswith(".toml"):
            return lock_name[len("pylock.") : -len(".toml")]
        return None

    @classmethod
    def load(
        cls,
        project_directory,  # type: str
        table_path,  # type: str
        config,  # type: Dict[str, Any]
    ):
        # type: (...) -> ScriptLock

        name = config.pop("name", None)
        if name is not None:
            if not isinstance(name, string):
                raise ConfigurationError(
                    "The {path} `name` value must be a string. Given {value} of type "
                    "{type}.".format(path=table_path, value=name, type=type(name).__name__)
                )
            # N.B.: Normalize "pylock.toml" to "" and "pylock.<name>.toml" to "<name>" and leave
            # anything else as-is.
            name = cls.lock_name(name) or name

        path = config.pop("path", "")
        if path:
            if not isinstance(path, string):
                raise ConfigurationError(
                    "The {path} `path` value must be a string. Given {value} of type "
                    "{type}.".format(path=table_path, value=path, type=type(path).__name__)
                )
            path = path if os.path.isabs(path) else os.path.join(project_directory, path)
            if not os.path.isfile(path):
                raise ConfigurationError(
                    "The {path} `path` of {value} does not point to an existing lock file.".format(
                        path=table_path, value=path
                    )
                )

        command = config.pop("command", [])
        if command and (
            not isinstance(command, list) or not all(isinstance(arg, string) for arg in command)
        ):
            raise ConfigurationError(
                "The {path} `command` value must be an array of strings. Given {value} of type "
                "{type}.".format(path=table_path, value=command, type=type(command).__name__)
            )

        if path and command:
            raise ConfigurationError(
                "You can either specify a lock `path` or a lock generating `command` for {path}, "
                "but not both.".format(path=table_path)
            )

        if not path and not command:
            raise ConfigurationError(
                "You must specify either a lock `path` or a lock generating `command` for "
                "{path}.".format(path=table_path)
            )

        if config:
            raise ConfigurationError(
                "The {path} table has {count} unrecognized configuration {keys}:\n"
                "{unrecognized_keys}".format(
                    path=table_path,
                    count=len(config),
                    keys=pluralize(config, "key"),
                    unrecognized_keys="\n".join(config),
                )
            )

        if path:
            if name is None:
                name = cls.lock_name(path)
                if name is None:
                    raise ConfigurationError(
                        "The lock `path` defined at {path} does not have a valid name for use as "
                        "an embedded lock file.\n"
                        "Specify a valid `name` for this lock file to be "
                        "embedded as. Either '' or 'pylock.toml' for the default lock, or '<name>' "
                        "or 'pylock.<name>.toml' for a console script specific lock."
                    )
            return cls(name=name, lock=path)
        else:
            return cls(name=name or "", lock=Command(args=tuple(command)))

    lock = attr.ib()  # type: Union[Text, Command]
    name = attr.ib(default="")  # type: str

    def materialize_lock(self, dest_dir):
        # type: (str) -> None

        lock_dest_path = os.path.join(dest_dir, self.file_name(self.name))
        if isinstance(self.lock, string):
            # MyPy can't follow the isinstance guard check above.
            safe_copy(self.lock, lock_dest_path)  # type: ignore[arg-type]
            return

        substitute_dest = functools.partial(
            text.format,
            name=self.name,
            dest_dir=dest_dir,
            lock_path=lock_dest_path,
            sys_executable=sys.executable,
        )
        try:
            subprocess.check_call(
                args=[substitute_dest(arg) for arg in cast(Command, self.lock).args]
            )
        except CalledProcessError as e:
            raise BuildError(
                "Failed to generate {lock_file}: {err}".format(
                    lock_file=os.path.basename(lock_dest_path), err=e
                )
            )


@attr.s(frozen=True)
class ScriptLocks(object):
    CONFIG_KEY = "script-locks"

    @classmethod
    def load(
        cls,
        project_directory,  # type: str
        config,  # type: Any
    ):
        # type: (...) -> Optional[ScriptLocks]

        if not config:
            return None

        if not isinstance(config, list) or not all(isinstance(item, dict) for item in config):
            raise ConfigurationError(
                "The [tool.pex.build_backend] `{key}` value must be an array of tables. "
                "Given {value} of type {type}.".format(
                    key=cls.CONFIG_KEY, value=config, type=type(config).__name__
                )
            )

        script_locks = defaultdict(list)  # type: DefaultDict[str, List[ScriptLock]]
        for index, item in enumerate(config):
            lock = ScriptLock.load(
                project_directory=project_directory,
                table_path="[tool.pex.build_backend.{key}][{index}]".format(
                    key=cls.CONFIG_KEY, index=index
                ),
                config=item,
            )
            script_locks[lock.name].append(lock)

        duplicate_lock_names = [name for name, locks in script_locks.items() if len(locks) > 1]
        if duplicate_lock_names:
            raise ConfigurationError(
                "The following {locks} {have} more than one entry; lock names must be unique:\n"
                "{duplicate_locks}".format(
                    locks=pluralize(duplicate_lock_names, "lock"),
                    have="have" if len(duplicate_lock_names) > 1 else "has",
                    duplicate_locks="\n".join(
                        ScriptLock.file_name(name) for name in duplicate_lock_names
                    ),
                )
            )

        return cls(locks=tuple(itertools.chain.from_iterable(script_locks.values())))

    locks = attr.ib()  # type: Tuple[ScriptLock, ...]

    def modify_sdist(self, sdist_dir):
        # type: (str) -> None
        for lock in self.locks:
            lock.materialize_lock(sdist_dir)

    def modify_wheel(
        self,
        wheel_dir,  # type: str
        dist_info_dir_relpath,  # type: str
    ):
        # type: (...) -> None
        dest_dir = safe_mkdir(os.path.join(wheel_dir, dist_info_dir_relpath, "pylock"))
        for lock in self.locks:
            lock.materialize_lock(dest_dir)
