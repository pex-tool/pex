# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import re

from colors import green

from pex.cli.testing import run_pex3
from pex.resolve.lockfile import json_codec
from pex.testing import run_pex_command


def test_preserve_pip_download_log():
    # type: () -> None

    result = run_pex3("lock", "create", "ansicolors==1.1.8", "--preserve-pip-download-log")
    result.assert_success()

    match = re.search(r"^pex: Preserving `pip download` log at (?P<log_path>.*)\.$", result.error)
    assert match is not None
    log_path = match.group("log_path")
    assert os.path.exists(log_path)
    expected_url = (
        "https://files.pythonhosted.org/packages/53/18/"
        "a56e2fe47b259bb52201093a3a9d4a32014f9d85071ad07e9d60600890ca/"
        "ansicolors-1.1.8-py2.py3-none-any.whl"
    )
    expected_algorithm = "sha256"
    expected_hash = "00d2dde5a675579325902536738dd27e4fac1fd68f773fe36c21044eb559e187"
    with open(log_path) as fp:
        assert (
            "Added ansicolors==1.1.8 from {url}#{algorithm}={hash} to build tracker".format(
                url=expected_url, algorithm=expected_algorithm, hash=expected_hash
            )
            in fp.read()
        )

    lockfile = json_codec.loads(result.output)
    assert 1 == len(lockfile.locked_resolves)

    locked_resolve = lockfile.locked_resolves[0]
    assert 1 == len(locked_resolve.locked_requirements)

    locked_requirement = locked_resolve.locked_requirements[0]
    artifacts = tuple(locked_requirement.iter_artifacts())
    assert 1 == len(artifacts)

    artifact = artifacts[0]
    assert expected_url == artifact.url
    assert expected_algorithm == artifact.fingerprint.algorithm
    assert expected_hash == artifact.fingerprint.hash


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
    ) == result.error
