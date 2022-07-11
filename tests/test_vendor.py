# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys

from pex.common import touch
from pex.typing import TYPE_CHECKING
from pex.vendor import VendorSpec

if TYPE_CHECKING:
    from typing import Any


def test_pinned():
    # type: () -> None
    vendor_spec = VendorSpec.pinned("foo", "1.2.3")
    assert "foo" == vendor_spec.key
    assert "foo==1.2.3" == vendor_spec.requirement


def test_git():
    # type: () -> None
    vendor_spec = VendorSpec.git(
        repo="https://github.com/foo.git", commit="da39a3ee", project_name="bar"
    )
    assert "bar" == vendor_spec.key
    assert "git+https://github.com/foo.git@da39a3ee#egg=bar" == vendor_spec.requirement
    assert "git+https://github.com/foo.git@da39a3ee#egg=bar" == vendor_spec.prepare()


def test_git_prep_command(tmpdir):
    # type: (Any) -> None
    repo = os.path.join(str(tmpdir), "repo")
    subprocess.check_call(["git", "init", repo])
    assert os.path.isdir(repo)

    subprocess.check_call(["git", "config", "user.email", "you@example.com"], cwd=repo)
    subprocess.check_call(["git", "config", "user.name", "Your Name"], cwd=repo)

    touch(os.path.join(repo, "README"))
    subprocess.check_call(["git", "add", "README"], cwd=repo)
    subprocess.check_call(["git", "commit", "-m", "Initial Commit."], cwd=repo)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo).decode("utf-8").strip()

    prep_file = os.path.join(repo, "prep")
    assert not os.path.exists(prep_file)

    vendor_spec = VendorSpec.git(
        repo=repo,
        commit=commit,
        project_name="bar",
        prep_command=[sys.executable, "-c", "fp = open('prep', 'w'); fp.close()"],
    )
    assert not os.path.exists(prep_file)

    assert "git+{repo}@{commit}#egg=bar".format(repo=repo, commit=commit) == vendor_spec.requirement
    assert not os.path.exists(prep_file)

    clone = vendor_spec.prepare()
    assert (
        commit
        == subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=clone).decode("utf-8").strip()
    )
    assert not os.path.exists(prep_file)
    assert os.path.isfile(os.path.join(clone, "prep"))
