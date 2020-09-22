# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager
from io import open

from pex.common import temporary_dir
from pex.pex_builder import PEXBuilder
from pex.testing import run_simple_pex
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterator, Text


@contextmanager
def write_and_run_simple_pex(inheriting):
    # type: (str) -> Iterator[Text]
    """Write a pex file that contains an executable entry point.

    :param inheriting: whether this pex should inherit site-packages paths.
    """
    with temporary_dir() as td:
        pex_path = os.path.join(td, "show_path.pex")
        with open(os.path.join(td, "exe.py"), "w") as fp:
            fp.write("")  # No contents, we just want the startup messages

        pb = PEXBuilder(path=td, preamble=None)
        pb.info.inherit_path = inheriting
        pb.set_executable(os.path.join(td, "exe.py"))
        pb.freeze()
        pb.build(pex_path)
        stdout, _ = run_simple_pex(pex_path, env={"PEX_VERBOSE": "1"})
        yield stdout.decode("utf-8")


def test_inherits_path_fallback_option():
    with write_and_run_simple_pex(inheriting="fallback") as so:
        assert "Scrubbing from user site" not in so, "User packages should not be scrubbed."
        assert "Scrubbing from site-packages" not in so, "Site packages should not be scrubbed."


def test_inherits_path_prefer_option():
    with write_and_run_simple_pex(inheriting="prefer") as so:
        assert "Scrubbing from user site" not in so, "User packages should not be scrubbed."
        assert "Scrubbing from site-packages" not in so, "Site packages should not be scrubbed."


def test_does_not_inherit_path_option():
    with write_and_run_simple_pex(inheriting="false") as so:
        assert "Scrubbing from user site" in so, "User packages should be scrubbed."
        assert "Scrubbing from site-packages" in so, "Site packages should be scrubbed."
