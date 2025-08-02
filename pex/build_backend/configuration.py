# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import importlib
import os.path
from types import ModuleType
from typing import Callable, Text

from pex import toml
from pex.build_backend import BuildError
from pex.common import pluralize
from pex.compatibility import string
from pex.lang import qualified_name
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict, Iterable, Iterator, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class ConfigurationError(BuildError):
    pass


@attr.s(frozen=True)
class Plugin(object):
    @classmethod
    def wrap(cls, plugin):
        # type: (Any) -> Plugin

        modify_sdist = getattr(plugin, "modify_sdist", None)
        if modify_sdist and not callable(modify_sdist):
            raise ConfigurationError(
                "The `modify_sdist` attribute of pex.build_backend.wrap plugin {plugin} must be a "
                "callable but given {value} of type {type}.".format(
                    plugin=qualified_name(plugin),
                    value=modify_sdist,
                    type=type(modify_sdist).__name__,
                )
            )

        modify_wheel = getattr(plugin, "modify_wheel", None)
        if modify_wheel and not callable(modify_wheel):
            raise ConfigurationError(
                "The `modify_wheel` attribute of pex.build_backend.wrap plugin {plugin} must be a "
                "callable but given {value} of type {type}.".format(
                    plugin=qualified_name(plugin),
                    value=modify_sdist,
                    type=type(modify_sdist).__name__,
                )
            )

        if not modify_sdist and not modify_wheel:
            raise ConfigurationError(
                "The pex.build_backend.wrap plugin {plugin} must define a `modify_sdist` function, "
                "a `modify_wheel` or both; it has neither.".format(plugin=qualified_name(plugin))
            )

        return cls(modify_sdist=modify_sdist, modify_wheel=modify_wheel)

    _modify_sdist = attr.ib()  # type: Optional[Callable[[str], None]]
    _modify_wheel = attr.ib()  # type: Optional[Callable[[str, str], None]]

    @property
    def modifies_sdists(self):
        # type: () -> bool
        return self._modify_sdist is not None

    def modify_sdist(self, sdist_dir):
        # type: (str) -> Any
        if self._modify_sdist:
            return self._modify_sdist(sdist_dir)
        return None

    @property
    def modifies_wheels(self):
        # type: () -> bool
        return self._modify_wheel is not None

    def modify_wheel(
        self,
        wheel_dir,  # type: str
        dist_info_dir_relpath,  # type: str
    ):
        # type: (...) -> Any
        if self._modify_wheel:
            return self._modify_wheel(wheel_dir, dist_info_dir_relpath)
        return None


def _check_plugin(
    plugin,  # type: Any
    project_directory,  # type: str
    config=None,  # type: Any
):
    # type: (...) -> Optional[Plugin]

    load = getattr(plugin, "load", None)
    if load:
        if not callable(load):
            raise ConfigurationError(
                "The `load` attribute of pex.build_backend.wrap plugin {plugin} must be a function "
                "that accepts a project_directory str and a config dict and returns a configured "
                "plugin object. Given `load` value {load} of type {type}".format(
                    plugin=qualified_name(plugin), load=load, type=type(load)
                )
            )
        plugin = load(project_directory=project_directory, config=config)
        if plugin is None:
            return None
    elif config is not None:
        raise ConfigurationError(
            "There was configuration data for pex.build_backend.wrap plugin {plugin} but the "
            "plugin has no load function to configure the plugin with the configuration "
            "data.".format(plugin=qualified_name(plugin))
        )
    return Plugin.wrap(plugin)


def _load_plugin(
    plugin_spec,  # type: Any
    project_directory,  # type: str
    config=None,  # type: Any
):
    # type: (...) -> Optional[Plugin]

    if not isinstance(plugin_spec, string):
        return _check_plugin(plugin_spec, project_directory, config=config)

    try:
        return _check_plugin(importlib.import_module(plugin_spec), project_directory, config=config)
    except (ImportError, ConfigurationError):
        components = plugin_spec.split(".")
        if len(components) == 1:
            raise
        # For example, handle `a.module.Object.Inside` housed in `a/module.py`:
        for index in range(len(components) - 1):
            split_index = -(index + 1)
            try:
                plugin = importlib.import_module(".".join(components[:split_index]))
                for attribute in components[split_index:]:
                    plugin = getattr(plugin, attribute)
                return _check_plugin(plugin, project_directory, config=config)
            except (ImportError, ConfigurationError):
                continue
        raise


def _load_plugins(
    project_directory,  # type: str
    build_backend_config,  # type: Dict[str, Any]
    plugin_specs,  # type: Iterable[str]
    internal_plugins=(),  # type: Iterable[Tuple[str, Any]]
):
    # type: (...) -> Iterator[Plugin]

    for section_name, internal_plugin in internal_plugins:
        config = build_backend_config.pop(section_name, None)
        plugin = _load_plugin(internal_plugin, project_directory, config=config)
        if plugin:
            yield plugin

    for plugin_spec in plugin_specs:
        config = build_backend_config.pop(plugin_spec, None)
        plugin = _load_plugin(plugin_spec, project_directory, config=config)
        if plugin:
            yield plugin


@attr.s(frozen=True)
class Configuration(object):
    delegate_build_backend = attr.ib()  # type: Text
    deterministic = attr.ib(default=True)  # type: bool
    _plugins = attr.ib(default=())  # type: Tuple[Plugin, ...]

    @property
    def build_backend(self):
        # type: () -> ModuleType
        return importlib.import_module(self.delegate_build_backend)

    def export_build_backend_hooks(self, namespace):
        # type: (Dict[str, Any]) -> None
        namespace.update(
            (name, attribute)
            for name, attribute in vars(self.build_backend).items()
            if callable(attribute)
        )

    @property
    def plugins(self):
        # type: () -> Iterator[Plugin]
        for plugin in self._plugins:
            yield plugin


def load_config(
    path=None,  # type: Optional[str]
    internal_plugins=None,  # type: Optional[Iterable[Tuple[str, Any]]]
):
    # type: (...) -> Configuration

    project_directory = os.path.dirname(path) if path else os.getcwd()
    pyproject_data = toml.load(path or "pyproject.toml")
    build_backend_config = pyproject_data.get("tool", {}).get("pex", {}).get("build_backend", {})
    delegate_build_backend = build_backend_config.pop("delegate-build-backend", None)
    if not delegate_build_backend:
        raise ConfigurationError(
            "The pex.build_backend.wrap build-backend must be configured in a "
            "[tool.pex.build_backend] table with at least a `delegate-build-backend` entry "
            "specifying the build-backend to wrap."
        )

    if not isinstance(delegate_build_backend, string):
        raise ConfigurationError(
            "The [tool.pex.build_backend] `delegate-build-backend` value must be a string "
            "specifying a build backend module name to wrap. Given {value} of type {type}.".format(
                value=delegate_build_backend, type=type(delegate_build_backend).__name__
            )
        )

    if delegate_build_backend == "pex.build_backend.wrap":
        raise ConfigurationError(
            "The [tool.pex.build_backend] `delegate-build-backend` value must point to a "
            "build-backend to wrap different from 'pex.build_backend.wrap'."
        )

    plugin_specs = build_backend_config.pop("plugins", [])
    if not isinstance(plugin_specs, list) or not all(
        isinstance(item, string) for item in plugin_specs
    ):
        raise ConfigurationError(
            "The [tool.pex.build_backend] `plugins` value must be a list of strings specifying "
            "importable custom build plugins to load. Given {value} of type {type}.".format(
                value=plugin_specs, type=type(plugin_specs).__name__
            )
        )

    plugins = tuple(
        _load_plugins(
            project_directory,
            build_backend_config,
            plugin_specs,
            internal_plugins=internal_plugins or (),
        )
    )

    if build_backend_config:
        raise ConfigurationError(
            "The [tool.pex.build_backend] table has {count} unrecognized configuration {keys}:\n"
            "{unrecognized_keys}".format(
                count=len(build_backend_config),
                keys=pluralize(build_backend_config, "key"),
                unrecognized_keys="\n".join(build_backend_config),
            )
        )

    return Configuration(delegate_build_backend=delegate_build_backend, plugins=plugins)
