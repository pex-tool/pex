# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex import toml
from testing.pytest_utils.tmp import Tempdir


def test_roundtrip(tmpdir):
    # type: (Tempdir) -> None

    data = {
        "top-level-key": ["a", "b", "c"],
        "second": {"more-nest": 1 / 137, "on": True, "age": 53},
    }

    assert data == toml.loads(toml.dumps(data))

    with open(tmpdir.join("example.toml"), "wb+") as fp:
        toml.dump(data, fp)
        fp.flush()
        fp.seek(0)
        assert data == toml.load(fp)
