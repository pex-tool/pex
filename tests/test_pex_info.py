# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import warnings

import pytest

from pex.common import temporary_dir
from pex.orderedset import OrderedSet
from pex.pex_info import PexInfo
from pex.pex_warnings import PEXWarning
from pex.typing import TYPE_CHECKING
from pex.variables import Variables
from pex.version import __version__ as pex_version

if TYPE_CHECKING:
    from typing import Dict, List, Text


def test_backwards_incompatible_pex_info():
    # type: () -> None

    def make_pex_info(requirements):
        # type: (List[Text]) -> PexInfo
        return PexInfo(info={"requirements": requirements})

    # forwards compatibility
    pi = make_pex_info(["hello"])
    assert pi.requirements == OrderedSet(["hello"])

    pi = make_pex_info(["hello==0.1", "world==0.2"])
    assert pi.requirements == OrderedSet(["hello==0.1", "world==0.2"])

    # malformed
    with pytest.raises(ValueError):
        make_pex_info("hello")  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        make_pex_info([("hello", False)])  # type: ignore[list-item]

    # backwards compatibility
    pi = make_pex_info(
        [
            ["hello==0.1", False, None],  # type: ignore[list-item]
            ["world==0.2", False, None],  # type: ignore[list-item]
        ]
    )
    assert pi.requirements == OrderedSet(["hello==0.1", "world==0.2"])


def assert_same_info(expected, actual):
    # type: (PexInfo, PexInfo) -> None
    assert expected.dump(sort_keys=True) == actual.dump(sort_keys=True)


def test_from_empty_env():
    # type: () -> None
    environ = Variables(environ={})
    info = {}  # type: Dict
    assert_same_info(PexInfo(info=info), PexInfo.from_env(env=environ))


def test_from_env():
    # type: () -> None
    with temporary_dir() as td:
        pex_root = os.path.realpath(os.path.join(td, "pex_root"))
        environ = dict(
            PEX_ROOT=pex_root,
            PEX_MODULE="entry:point",
            PEX_SCRIPT="script.sh",
            PEX_FORCE_LOCAL="true",
            PEX_UNZIP="true",
            PEX_INHERIT_PATH="prefer",
            PEX_IGNORE_ERRORS="true",
            PEX_ALWAYS_CACHE="true",
        )

        info = dict(
            pex_root=pex_root,
            entry_point="entry:point",
            script="script.sh",
            zip_safe=False,
            unzip=True,
            inherit_path=True,
            ignore_errors=True,
            always_write_cache=True,
        )

    assert_same_info(PexInfo(info=info), PexInfo.from_env(env=Variables(environ=environ)))


def test_build_properties():
    # type: () -> None
    assert pex_version == PexInfo.default().build_properties["pex_version"]


def test_merge_split():
    # type: () -> None
    path_1, path_2 = "/pex/path/1:/pex/path/2", "/pex/path/3:/pex/path/4"
    result = PexInfo._merge_split(path_1, path_2)
    assert result == ["/pex/path/1", "/pex/path/2", "/pex/path/3", "/pex/path/4"]

    path_1, path_2 = "/pex/path/1:", "/pex/path/3:/pex/path/4"
    result = PexInfo._merge_split(path_1, path_2)
    assert result == ["/pex/path/1", "/pex/path/3", "/pex/path/4"]

    path_1, path_2 = "/pex/path/1::/pex/path/2", "/pex/path/3:/pex/path/4"
    result = PexInfo._merge_split(path_1, path_2)
    assert result == ["/pex/path/1", "/pex/path/2", "/pex/path/3", "/pex/path/4"]

    path_1, path_2 = "/pex/path/1::/pex/path/2", "/pex/path/3:/pex/path/4"
    result = PexInfo._merge_split(path_1, None)
    assert result == ["/pex/path/1", "/pex/path/2"]
    result = PexInfo._merge_split(None, path_2)
    assert result == ["/pex/path/3", "/pex/path/4"]


def test_pex_root_set_none():
    # type: () -> None
    pex_info = PexInfo.default()
    pex_info.pex_root = None

    assert PexInfo.default().pex_root == pex_info.pex_root
    assert os.path.expanduser("~/.pex") == pex_info.pex_root


def test_pex_root_set_unwriteable():
    # type: () -> None
    with temporary_dir() as td:
        pex_root = os.path.realpath(os.path.join(td, "pex_root"))
        os.mkdir(pex_root, 0o444)

        pex_info = PexInfo.default()
        pex_info.pex_root = pex_root

        with warnings.catch_warnings(record=True) as log:
            assert pex_root != pex_info.pex_root

        assert 1 == len(log)
        message = log[0].message
        assert isinstance(message, PEXWarning)
        assert pex_root in str(message)
        assert pex_info.pex_root in str(message)
