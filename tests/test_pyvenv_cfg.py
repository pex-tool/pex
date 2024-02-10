# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
from textwrap import dedent

import pytest

from pex.common import touch
from pex.interpreter import PyVenvCfg
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_parse_invalid(tmpdir):
    # type: (Any) -> None

    pyvenv_cfg = os.path.join(str(tmpdir), "pyvenv.cfg")
    touch(pyvenv_cfg)
    with pytest.raises(PyVenvCfg.Error):
        PyVenvCfg.parse(pyvenv_cfg)


def test_parse_nominal(tmpdir):
    # type: (Any) -> None

    pyvenv_cfg = os.path.join(str(tmpdir), "pyvenv.cfg")
    with open(pyvenv_cfg, "w") as fp:
        fp.write(
            dedent(
                """\
                home = foo
                include-system-site-packages = true
                version = 1.2.3
                """
            )
        )

    cfg = PyVenvCfg.parse(pyvenv_cfg)
    assert pyvenv_cfg == cfg.path
    assert "foo" == cfg.home
    assert cfg.include_system_site_packages is True
    assert "1.2.3" == cfg.config("version")
    assert cfg.config("bar") is None
    assert "baz" == cfg.config("bar", "baz")


def test_find_not_found(tmpdir):
    # type: (Any) -> None

    python = os.path.join(str(tmpdir), "bin", "python")
    touch(python)
    assert PyVenvCfg.find(python) is None


def test_find_python_sibling(tmpdir):
    # type: (Any) -> None

    bin_dir = os.path.join(str(tmpdir), "bin")
    python = os.path.join(bin_dir, "python")
    touch(python)
    with open(os.path.join(bin_dir, "pyvenv.cfg"), "w") as fp:
        fp.write("home = foo")
    cfg = PyVenvCfg.find(python)
    assert cfg is not None
    assert "foo" == cfg.home


def test_find_venv_sibling(tmpdir):
    # type: (Any) -> None

    python = os.path.join(str(tmpdir), "bin", "python")
    touch(python)
    with open(os.path.join(str(tmpdir), "pyvenv.cfg"), "w") as fp:
        fp.write("home = foo")
    cfg = PyVenvCfg.find(python)
    assert cfg is not None
    assert "foo" == cfg.home
