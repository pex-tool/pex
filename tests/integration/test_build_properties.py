# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os.path
import subprocess

from pex.common import safe_mkdir
from pex.pex_info import PexInfo
from pex.version import __version__
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir


def test_build_properties_from_file(tmpdir):
    # type: (Tempdir) -> None

    with open(tmpdir.join("build-properties.json"), "w") as fp:
        json.dump(
            {
                "foo": "bar",
                "spam": ["eggs", 42],
            },
            fp,
        )

    pex = tmpdir.join("pex")
    run_pex_command(args=["--build-properties", fp.name, "-o", pex]).assert_success()
    assert {
        "pex_version": __version__,
        "foo": "bar",
        "spam": ["eggs", 42],
    } == PexInfo.from_pex(pex).build_properties


def test_build_properties_from_blob(tmpdir):
    # type: (Tempdir) -> None

    pex = tmpdir.join("pex")
    run_pex_command(
        args=[
            "--build-properties",
            json.dumps(
                {
                    "foo": "bar",
                    "spam": ["eggs", 42],
                }
            ),
            "-o",
            pex,
        ]
    ).assert_success()
    assert {
        "pex_version": __version__,
        "foo": "bar",
        "spam": ["eggs", 42],
    } == PexInfo.from_pex(pex).build_properties


def test_build_properties_from_entries(tmpdir):
    # type: (Tempdir) -> None

    pex = tmpdir.join("pex")
    run_pex_command(
        args=["--build-property", "foo=bar", "--build-property", 'spam=["eggs",42]', "-o", pex]
    ).assert_success()
    assert {
        "pex_version": __version__,
        "foo": "bar",
        "spam": ["eggs", 42],
    } == PexInfo.from_pex(pex).build_properties


def test_build_properties_mixed(tmpdir):
    # type: (Tempdir) -> None

    pex = tmpdir.join("pex")
    run_pex_command(
        args=[
            "--build-properties",
            json.dumps(
                {
                    "foo": "bar",
                    "spam": ["eggs", 42],
                }
            ),
            "--build-property",
            "foo=baz",
            "--build-property",
            'extra={"a":"b","c":4}',
            "-o",
            pex,
        ]
    ).assert_success()
    assert {
        "pex_version": __version__,
        "foo": "baz",
        "spam": ["eggs", 42],
        "extra": {"a": "b", "c": 4},
    } == PexInfo.from_pex(pex).build_properties


def test_build_properties_git_state(tmpdir):
    # type: (Tempdir) -> None

    project_dir = safe_mkdir(tmpdir.join("project"))
    with open(os.path.join(project_dir, "build-properties.json"), "w") as fp:
        json.dump({"baz": "spam"}, fp)

    subprocess.check_call(["git", "init", "-b", "trunk", project_dir])
    subprocess.check_call(["git", "config", "user.email", "fred@example.com"], cwd=project_dir)
    subprocess.check_call(["git", "config", "user.name", "Fred Bob"], cwd=project_dir)
    subprocess.check_call(["git", "add", "."], cwd=project_dir)
    subprocess.check_call(
        ["git", "commit", "--no-gpg-sign", "-m", "Initial Commit."], cwd=project_dir
    )
    commit = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project_dir)
        .decode("utf-8")
        .strip()
    )

    pex = tmpdir.join("pex")

    run_pex_command(
        args=["--record-git-state", "--build-property", "foo=bar", "-o", pex], cwd=project_dir
    ).assert_success()
    assert {
        "pex_version": __version__,
        "foo": "bar",
        "git_state": {"commit": commit, "description": commit[:7], "branch": "trunk", "tag": ""},
    } == PexInfo.from_pex(pex).build_properties

    subprocess.check_call(
        ["git", "tag", "--no-sign", "-m", "Initial Tag.", "Slartibartfast"], cwd=project_dir
    )
    run_pex_command(
        args=["--record-git-state", "--build-properties", fp.name, "-o", pex], cwd=project_dir
    ).assert_success()
    assert {
        "pex_version": __version__,
        "baz": "spam",
        "git_state": {
            "commit": commit,
            "description": "Slartibartfast-0-g{abbrev_commit}".format(abbrev_commit=commit[:7]),
            "branch": "trunk",
            "tag": "Slartibartfast",
        },
    } == PexInfo.from_pex(pex).build_properties
