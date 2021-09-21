# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import subprocess
import sys

from pex.locked_resolve import Fingerprint
from pex.requirements import LogicalLine, PyPIRequirement, parse_requirement_file
from pex.testing import IntegResults, make_env
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Iterator, Optional, Set, Text


def run_pex3(
    *args,  # type: str
    **env  # type: Optional[str]
):
    # type: (...) -> IntegResults
    process = subprocess.Popen(
        args=[sys.executable, "-mpex.cli"] + list(args),
        env=make_env(**env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate()
    return IntegResults(
        output=stdout.decode("utf-8"), error=stderr.decode("utf-8"), return_code=process.returncode
    )


def strip_comments(text):
    # type: (Text) -> Text
    return "".join(re.sub(r"#.*$", "", line) for line in text.splitlines(keepends=True))


def assert_equivalent_requirements(
    expected,  # type: Text
    actual,  # type: Text
):
    # type: (...) -> None
    assert strip_comments(expected) == strip_comments(actual)


def test_create(tmpdir):
    # type: (Any) -> None

    lock_file = os.path.join(str(tmpdir), "requirements.lock.txt")
    run_pex3("lock", "create", "ansicolors", "-o", lock_file).assert_success()

    # We should get back the same lock given a lock as input mod comments (in particular the via
    # comment line which is sensitive to the source of the requirements)
    result = run_pex3("lock", "create", "-r", lock_file)
    result.assert_success()
    with open(lock_file) as fp:
        assert_equivalent_requirements(expected=fp.read(), actual=result.output)


def parse_hashes(line):
    # type: (LogicalLine) -> Iterator[Fingerprint]
    for match in re.finditer(
        r"--hash:(?P<algorithm>[^=]+)=(?P<hash>[0-9a-f]+)", str(line.raw_text)
    ):
        yield Fingerprint(match.group("algorithm"), match.group("hash"))


def test_create_style(tmpdir):
    # type: (Any) -> None

    def create_lock(style):
        # type: (str) -> Set[Fingerprint]
        lock_file = os.path.join(str(tmpdir), "{}.lock".format(style))
        run_pex3(
            "lock", "create", "ansicolors==1.1.8", "-o", lock_file, "--style", style
        ).assert_success()
        requirements = []
        for item in parse_requirement_file(lock_file):
            assert isinstance(item, PyPIRequirement)
            requirements.append(item)
        assert 1 == len(requirements)
        return set(parse_hashes(requirements[0].line))

    strict_hashes = create_lock("strict")
    sources_hashes = create_lock("sources")

    # We should have 1 hash for the strict lock and 2 hashes for sources lock since we know
    # ansicolors 1.1.8 provides both a universal wheel and an sdist.
    assert 1 == len(strict_hashes)
    assert 2 == len(sources_hashes)

    # The strict and sources locks should share the wheel hash in common.
    assert strict_hashes == strict_hashes & sources_hashes
