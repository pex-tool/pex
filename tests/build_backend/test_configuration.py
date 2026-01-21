# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re
from textwrap import dedent

import pytest

from pex.build_backend.configuration import Configuration, ConfigurationError, load_config
from pex.compatibility import text
from pex.typing import TYPE_CHECKING
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Any, Dict, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class WriteConfig(object):
    _tmpdir = attr.ib()  # type: Tempdir

    def __call__(
        self, text, *internal_plugins  # type: Tuple[str, Any]
    ):
        # type: (...) -> Configuration
        with open(self._tmpdir.join("pyproject.toml"), "w") as fp:
            fp.write(text)
        return load_config(fp.name, internal_plugins=internal_plugins)


@pytest.fixture
def write_config(tmpdir):
    # type: (Tempdir) -> WriteConfig

    return WriteConfig(tmpdir)


def test_load_config_circular_not_allowed(write_config):
    # type: (WriteConfig) -> None

    with pytest.raises(
        ConfigurationError,
        match=re.escape(
            "The [tool.pex.build_backend] `delegate-build-backend` value must point to a "
            "build-backend to wrap different from 'pex.build_backend.wrap'."
        ),
    ):
        write_config(
            dedent(
                """\
                [tool.pex.build_backend]
                delegate-build-backend = "pex.build_backend.wrap"
                """
            )
        )


def test_load_config_no_plugins(write_config):
    # type: (WriteConfig) -> None

    config = write_config(
        dedent(
            """\
            [tool.pex.build_backend]
            delegate-build-backend = "setuptools.build_meta"
            """
        )
    )
    assert "setuptools.build_meta" == config.delegate_build_backend
    assert () == tuple(config.plugins)


def test_load_config_no_plugins_unconfigured_internal_plugin(write_config):
    # type: (WriteConfig) -> None

    class Plugin(object):
        @classmethod
        def load(
            cls,
            project_directory,  # type: str
            config,  # type: Any
        ):
            # type: (...) -> None
            assert os.path.isfile(os.path.join(project_directory, "pyproject.toml"))
            assert config is None
            return None

    config = write_config(
        dedent(
            """\
            [tool.pex.build_backend]
            delegate-build-backend = "setuptools.build_meta"
            """
        ),
        ("plugin", Plugin),
    )
    assert "setuptools.build_meta" == config.delegate_build_backend
    assert () == tuple(config.plugins)


def test_load_config_no_plugins_internal_plugin_self_disabled(write_config):
    # type: (WriteConfig) -> None

    class Plugin(object):
        @classmethod
        def load(
            cls,
            project_directory,  # type: str
            config,  # type: Any
        ):
            # type: (...) -> None
            assert os.path.isfile(os.path.join(project_directory, "pyproject.toml"))
            assert {"foo": "bar"} == config
            return None

    config = write_config(
        dedent(
            """\
            [tool.pex.build_backend]
            delegate-build-backend = "setuptools.build_meta"

            [tool.pex.build_backend.plugin]
            foo = "bar"
            """
        ),
        ("plugin", Plugin),
    )
    assert "setuptools.build_meta" == config.delegate_build_backend
    assert () == tuple(config.plugins)


def test_load_config_plugin_configured(write_config):
    # type: (WriteConfig) -> None

    @attr.s(frozen=True)
    class Plugin(object):
        @classmethod
        def load(
            cls,
            project_directory,  # type: str
            config,  # type: Any
        ):
            # type: (...) -> Plugin
            assert os.path.isfile(os.path.join(project_directory, "pyproject.toml"))
            assert isinstance(config, dict) and all(isinstance(key, text) for key in config)
            return cls(config)

        config = attr.ib()  # type: Dict[str, Any]

        def modify_sdist(self, sdist_dir):
            # type: (str) -> Any
            return self.config[sdist_dir]

        def modify_wheel(
            self,
            wheel_dir,  # type: str
            dist_info_dir_relpath,  # type: str
        ):
            # type: (...) -> Any
            return self.config[wheel_dir][dist_info_dir_relpath]

    config = write_config(
        dedent(
            """\
            [tool.pex.build_backend]
            delegate-build-backend = "setuptools.build_meta"

            [tool.pex.build_backend.plugin]
            foo = "bar"
            baz = { spam = "eggs" }
            """
        ),
        ("plugin", Plugin),
    )
    assert "setuptools.build_meta" == config.delegate_build_backend

    plugins = tuple(config.plugins)
    assert len(plugins) == 1
    plugin = plugins[0]

    assert plugin.modifies_sdists
    assert "bar" == plugin.modify_sdist("foo")
    assert plugin.modifies_wheels
    assert "eggs" == plugin.modify_wheel("baz", "spam")


def test_load_config_plugin_sdist(write_config):
    # type: (WriteConfig) -> None

    class Plugin(object):
        @staticmethod
        def modify_sdist(sdist_dir):
            # type: (str) -> Any
            return sdist_dir

    config = write_config(
        dedent(
            """\
            [tool.pex.build_backend]
            delegate-build-backend = "setuptools.build_meta"
            """
        ),
        ("plugin", Plugin),
    )
    assert "setuptools.build_meta" == config.delegate_build_backend

    plugins = tuple(config.plugins)
    assert len(plugins) == 1
    plugin = plugins[0]

    assert plugin.modifies_sdists
    assert "foo" == plugin.modify_sdist("foo")
    assert not plugin.modifies_wheels
    assert plugin.modify_wheel("foo", "bar") is None


def test_load_config_plugin_wheel(write_config):
    # type: (WriteConfig) -> None

    class Plugin(object):
        @staticmethod
        def modify_wheel(
            wheel_dir,  # type: str
            dist_info_dir_relpath,  # type: str
        ):
            # type: (...) -> Any
            return wheel_dir, dist_info_dir_relpath

    config = write_config(
        dedent(
            """\
            [tool.pex.build_backend]
            delegate-build-backend = "setuptools.build_meta"
            """
        ),
        ("plugin", Plugin),
    )
    assert "setuptools.build_meta" == config.delegate_build_backend

    plugins = tuple(config.plugins)
    assert len(plugins) == 1
    plugin = plugins[0]

    assert plugin.modifies_wheels
    assert ("foo", "bar") == plugin.modify_wheel("foo", "bar")
    assert not plugin.modifies_sdists
    assert plugin.modify_sdist("foo") is None


def test_load_config_plugin_both(write_config):
    # type: (WriteConfig) -> None

    class Plugin(object):
        @staticmethod
        def modify_sdist(sdist_dir):
            # type: (str) -> Any
            return sdist_dir

        @staticmethod
        def modify_wheel(
            wheel_dir,  # type: str
            dist_info_dir_relpath,  # type: str
        ):
            # type: (...) -> Any
            return wheel_dir, dist_info_dir_relpath

    config = write_config(
        dedent(
            """\
            [tool.pex.build_backend]
            delegate-build-backend = "setuptools.build_meta"
            """
        ),
        ("plugin", Plugin),
    )
    assert "setuptools.build_meta" == config.delegate_build_backend

    plugins = tuple(config.plugins)
    assert len(plugins) == 1
    plugin = plugins[0]

    assert plugin.modifies_sdists
    assert "foo" == plugin.modify_sdist("foo")
    assert plugin.modifies_wheels
    assert ("foo", "bar") == plugin.modify_wheel("foo", "bar")


class InvalidPlugin(object):
    pass


def test_load_config_plugin_neither(write_config):
    # type: (WriteConfig) -> None

    with pytest.raises(
        ConfigurationError,
        match=re.escape(
            "The pex.build_backend.wrap plugin test_configuration.InvalidPlugin must define a "
            "`modify_sdist` function, a `modify_wheel` or both; it has neither."
        ),
    ):
        write_config(
            dedent(
                """\
                [tool.pex.build_backend]
                delegate-build-backend = "setuptools.build_meta"
                """
            ),
            ("plugin", InvalidPlugin),
        )


@attr.s(frozen=True)
class CustomPlugin(object):
    @attr.s(frozen=True)
    class Nested(object):
        @classmethod
        def load(
            cls,
            project_directory,  # type: str
            config,  # type: Any
        ):
            # type: (...) -> CustomPlugin.Nested
            assert os.path.isfile(os.path.join(project_directory, "pyproject.toml"))
            return cls(config)

        config = attr.ib()  # type: Any

        def modify_wheel(
            self,
            wheel_dir,  # type: str
            dist_info_dir_relpath,  # type: str
        ):
            # type: (...) -> Any
            return wheel_dir, dist_info_dir_relpath, self.config

    @classmethod
    def load(
        cls,
        project_directory,  # type: str
        config,  # type: Any
    ):
        # type: (...) -> CustomPlugin
        assert os.path.isfile(os.path.join(project_directory, "pyproject.toml"))
        return cls(config)

    config = attr.ib()  # type: Any

    def modify_sdist(self, sdist_dir):
        # type: (str) -> Any
        return sdist_dir, self.config


def test_load_config_custom_plugin(write_config):
    # type: (WriteConfig) -> None

    config = write_config(
        dedent(
            """\
            [tool.pex.build_backend]
            delegate-build-backend = "setuptools.build_meta"
            plugins = ["test_configuration.CustomPlugin"]
            """
        )
    )

    assert "setuptools.build_meta" == config.delegate_build_backend

    plugins = tuple(config.plugins)
    assert len(plugins) == 1
    plugin = plugins[0]

    assert plugin.modifies_sdists
    assert ("foo", None) == plugin.modify_sdist("foo")
    assert not plugin.modifies_wheels

    config = write_config(
        dedent(
            """\
            [tool.pex.build_backend]
            delegate-build-backend = "setuptools.build_meta"
            plugins = ["test_configuration.CustomPlugin"]

            [tool.pex.build_backend."test_configuration.CustomPlugin"]
            bar = 42
            """
        )
    )

    plugin = next(config.plugins)

    assert plugin.modifies_sdists
    assert ("foo", {"bar": 42}) == plugin.modify_sdist("foo")
    assert not plugin.modifies_wheels


def test_load_config_custom_plugin_nested(write_config):
    config = write_config(
        dedent(
            """\
            [tool.pex.build_backend]
            delegate-build-backend = "setuptools.build_meta"
            plugins = [
                "test_configuration.CustomPlugin",
                "test_configuration.CustomPlugin.Nested",
            ]

            [tool.pex.build_backend."test_configuration.CustomPlugin"]
            bar = 42

            [tool.pex.build_backend."test_configuration.CustomPlugin.Nested"]
            foo = true
            """
        )
    )

    plugins = tuple(config.plugins)
    plugin1, plugin2 = plugins

    assert plugin1.modifies_sdists
    assert ("foo", {"bar": 42}) == plugin1.modify_sdist("foo")
    assert not plugin1.modifies_wheels

    assert plugin2.modifies_wheels
    assert ("baz", "spam", {"foo": True}) == plugin2.modify_wheel("baz", "spam")
    assert not plugin2.modifies_sdists
