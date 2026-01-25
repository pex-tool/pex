# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os
import subprocess
from textwrap import dedent

import pytest

from pex.common import safe_mkdir, safe_open
from pex.compatibility import commonpath
from pex.os import Os
from pex.scie.model import DesktopFileParser
from pex.typing import TYPE_CHECKING
from testing import IS_LINUX, make_env, run_pex_command
from testing.pytest_utils.tmp import Tempdir
from testing.scie import skip_if_no_provider

if TYPE_CHECKING:
    from typing import Any, Dict


@skip_if_no_provider
def test_desktop_install(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    scie = tmpdir.join("cowsay")
    run_pex_command(
        args=[
            "--runtime-pex-root",
            pex_root,
            "cowsay<6",
            "-c",
            "cowsay",
            "-o",
            scie,
            "--scie",
            "eager",
            "--scie-only",
            "--scie-desktop-file",
        ]
    ).assert_success()

    xdg_data_home = safe_mkdir(tmpdir.join("XDG_DATA_HOME"))
    env = make_env(
        SCIE_BASE=tmpdir.join("nce"), XDG_DATA_HOME=xdg_data_home
    )  # type: Dict[str, Any]
    if Os.CURRENT is Os.LINUX:
        env.update(PEX_DESKTOP_INSTALL="0")
    assert b"| Moo! |" in subprocess.check_output(args=[scie, "Moo!"], env=env)
    assert [] == os.listdir(xdg_data_home)

    env.update(PEX_DESKTOP_INSTALL="1")
    assert b"| Moo! |" in subprocess.check_output(args=[scie, "Moo!"], env=env)
    if Os.CURRENT is Os.LINUX:
        assert [os.path.join(xdg_data_home, "applications", "cowsay.desktop")] == [
            os.path.join(root, f) for root, _, files in os.walk(xdg_data_home) for f in files
        ]

        env.update(PEX_DESKTOP_INSTALL="uninstall")
        assert b"| Moo! |" in subprocess.check_output(args=[scie, "Moo!"], env=env)
        assert ["applications"] == os.listdir(xdg_data_home)
        assert [] == os.listdir(os.path.join(xdg_data_home, "applications"))

        assert b"| Moo! |" in subprocess.check_output(
            args=[scie, "Moo!"], env=env
        ), "Expected a second uninstall to gracefully noop."
    else:
        assert [] == os.listdir(xdg_data_home)


@skip_if_no_provider
@pytest.mark.skipif(not IS_LINUX, reason="PEX scie desktop installs are only supported for Linux.")
def test_icon_file(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    icon = tmpdir.join("file.ico")
    icon_contents = "42"
    with safe_open(icon, "w") as fp:
        fp.write(icon_contents)

    scie = tmpdir.join("example")
    run_pex_command(
        args=[
            "--runtime-pex-root",
            pex_root,
            "cowsay<6",
            "-c",
            "cowsay",
            "--scie",
            "eager",
            "--scie-only",
            "--scie-icon",
            icon,
            "--no-scie-prompt-desktop-install",
            "-o",
            scie,
        ]
    ).assert_success()

    scie_base = tmpdir.join("nce")
    xdg_data_home = safe_mkdir(tmpdir.join("XDG_DATA_HOME"))
    env = make_env(SCIE_BASE=scie_base, XDG_DATA_HOME=xdg_data_home)
    assert b"| Moo! |" in subprocess.check_output(args=[scie, "Moo!"], env=env)

    parser = DesktopFileParser.create(
        os.path.join(xdg_data_home, "applications", "example.desktop")
    )
    assert "example" == parser.get("Desktop Entry", "Name")
    with open(parser.get("Desktop Entry", "Icon")) as fp:
        assert icon_contents == fp.read()
    assert scie_base == commonpath((scie_base, fp.name))


@skip_if_no_provider
@pytest.mark.skipif(not IS_LINUX, reason="PEX scie desktop installs are only supported for Linux.")
def test_icon_resource(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    src = tmpdir.join("src")
    icon = os.path.join(src, "example", "resource.ico")
    icon_contents = "42"
    with safe_open(icon, "w") as fp:
        fp.write(icon_contents)

    scie = tmpdir.join("example")
    run_pex_command(
        args=[
            "--runtime-pex-root",
            pex_root,
            "-D",
            src,
            "cowsay<6",
            "-c",
            "cowsay",
            "--scie",
            "eager",
            "--scie-only",
            "--scie-icon",
            "{scie.env.ICON}",
            "--scie-bind-resource",
            "ICON=example/resource.ico",
            "--no-scie-prompt-desktop-install",
            "-o",
            scie,
        ]
    ).assert_success()

    xdg_data_home = safe_mkdir(tmpdir.join("XDG_DATA_HOME"))
    env = make_env(SCIE_BASE=tmpdir.join("nce"), XDG_DATA_HOME=xdg_data_home)
    assert b"| Moo! |" in subprocess.check_output(args=[scie, "Moo!"], env=env)

    parser = DesktopFileParser.create(
        os.path.join(xdg_data_home, "applications", "example.desktop")
    )
    assert "example" == parser.get("Desktop Entry", "Name")
    with open(parser.get("Desktop Entry", "Icon")) as fp:
        assert icon_contents == fp.read()
    assert pex_root == commonpath((pex_root, fp.name))


@skip_if_no_provider
@pytest.mark.skipif(not IS_LINUX, reason="PEX scie desktop installs are only supported for Linux.")
def test_desktop_file(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    scie = tmpdir.join("cowsay")

    desktop_file = tmpdir.join("desktop.file")
    with open(desktop_file, "w") as fp:
        fp.write(
            dedent(
                """\
                [Test]
                Data={{"name": "{name}", "exe": "{exe}", "icon": "{icon}"}}

                [Desktop Entry]
                Name=Slartibartfast
                Icon=DoesNotExist.png
                """
            )
        )

    icon = tmpdir.join("file.ico")
    icon_contents = "1/137"
    with open(icon, "w") as fp:
        fp.write(icon_contents)

    run_pex_command(
        args=[
            "--runtime-pex-root",
            pex_root,
            "cowsay<6",
            "-c",
            "cowsay",
            "-o",
            scie,
            "--scie",
            "eager",
            "--scie-only",
            "--scie-icon",
            icon,
            "--scie-desktop-file",
            desktop_file,
            "--no-scie-prompt-desktop-install",
        ]
    ).assert_success()

    xdg_data_home = safe_mkdir(tmpdir.join("XDG_DATA_HOME"))
    scie_base = tmpdir.join("nce")
    env = make_env(SCIE_BASE=scie_base, XDG_DATA_HOME=xdg_data_home)
    assert b"| Moo! |" in subprocess.check_output(args=[scie, "Moo!"], env=env)

    parser = DesktopFileParser.create(os.path.join(xdg_data_home, "applications", "cowsay.desktop"))
    assert "Slartibartfast" == parser.get("Desktop Entry", "Name")
    assert "DoesNotExist.png" == parser.get("Desktop Entry", "Icon")

    data = json.loads(parser.get("Test", "Data"))
    assert parser.get("Desktop Entry", "Exec") == data.pop("exe")
    assert "cowsay" == data.pop("name")

    icon = data.pop("icon")
    assert scie_base == commonpath((scie_base, icon))
    with open(icon) as fp:
        assert icon_contents == fp.read()

    assert not data
