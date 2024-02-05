# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import re

import pytest
from colors import green

from pex.resolve.lockfile import json_codec
from pex.resolve.resolver_configuration import ResolverVersion
from testing import run_pex_command
from testing.cli import run_pex3


def test_preserve_pip_download_log():
    # type: () -> None

    result = run_pex3("lock", "create", "ansicolors==1.1.8", "--preserve-pip-download-log")
    result.assert_success()

    match = re.search(
        r"^pex: Preserving `pip download` log at (?P<log_path>.*)$", result.error, re.MULTILINE
    )
    assert match is not None
    log_path = match.group("log_path")
    assert os.path.exists(log_path)
    expected_url_suffix = "ansicolors-1.1.8-py2.py3-none-any.whl"
    expected_algorithm = "sha256"
    expected_hash = "00d2dde5a675579325902536738dd27e4fac1fd68f773fe36c21044eb559e187"
    with open(log_path) as fp:
        log_text = fp.read()

    assert re.search(
        # N.B.: Modern Pip excludes hashes from logged URLs when the index serves up PEP-691 json
        # responses.
        r"Added ansicolors==1\.1\.8 from https?://\S+/{url_suffix}(?:#{algorithm}={hash})? to build tracker".format(
            url_suffix=re.escape(expected_url_suffix),
            algorithm=re.escape(expected_algorithm),
            hash=re.escape(expected_hash),
        ),
        log_text,
    ) or re.search(
        # N.B.: Even more modern Pip does not log "Added ... to build tracker" lines for pre-built
        # wheels; so we look for an alternate expected log line.
        r"Looking up \"https?://\S+/{url_suffix}\" in the cache".format(
            url_suffix=re.escape(expected_url_suffix),
        ),
        log_text,
    )

    lockfile = json_codec.loads(result.output)
    assert 1 == len(lockfile.locked_resolves)

    locked_resolve = lockfile.locked_resolves[0]
    assert 1 == len(locked_resolve.locked_requirements)

    locked_requirement = locked_resolve.locked_requirements[0]
    artifacts = tuple(locked_requirement.iter_artifacts())
    assert 1 == len(artifacts)

    artifact = artifacts[0]
    assert artifact.url.download_url.endswith(expected_url_suffix)
    assert expected_algorithm == artifact.fingerprint.algorithm
    assert expected_hash == artifact.fingerprint.hash


@pytest.mark.skipif(
    ResolverVersion.default() is ResolverVersion.PIP_2020,
    reason=(
        "The PIP_2020 resolver triggers download analysis in normal resolves but this test is "
        "concerned with the case when there is no analysis to be performed."
    ),
)
def test_preserve_pip_download_log_none():
    # type: () -> None

    result = run_pex_command(
        args=[
            "ansicolors==1.1.8",
            "--preserve-pip-download-log",
            "--",
            "-c",
            "import colors; print(colors.green('42'))",
        ],
        quiet=True,
    )
    result.assert_success()
    assert green("42") == result.output.strip()
    assert (
        "pex: The `pip download` log is not being utilized, to see more `pip download` details, "
        "re-run with more Pex verbosity (more `-v`s).\n"
    ) in result.error, result.error
