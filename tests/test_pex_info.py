# Copyright 2015 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import warnings

import pytest

from pex.common import temporary_dir
from pex.inherit_path import InheritPath
from pex.interpreter_constraints import InterpreterConstraints
from pex.orderedset import OrderedSet
from pex.pex_info import PexInfo
from pex.pex_warnings import PEXWarning
from pex.typing import TYPE_CHECKING
from pex.variables import Variables
from pex.version import __version__ as pex_version
from testing.pytest_utils.tmp import Tempdir

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
    assert expected.dump() == actual.dump()


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
            PEX_INHERIT_PATH="prefer",
            PEX_IGNORE_ERRORS="true",
            # These are deprecated and should be ignored by PexInfo.
            PEX_ALWAYS_CACHE="true",
            PEX_FORCE_LOCAL="true",
            PEX_UNZIP="true",
        )
        with warnings.catch_warnings(record=True):
            env = Variables(environ=environ)

        info = dict(
            pex_root=pex_root,
            entry_point="entry:point",
            script="script.sh",
            inherit_path=True,
            ignore_errors=True,
        )

    assert_same_info(PexInfo(info=info), PexInfo.from_env(env=env))


def test_build_properties():
    # type: () -> None
    assert pex_version == PexInfo.default().build_properties["pex_version"]


def test_pex_root_set_unwriteable(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex_root")
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


def test_copy():
    # type: () -> None
    default_info = PexInfo.default()
    default_info_copy = default_info.copy()
    assert default_info is not default_info_copy
    assert default_info.dump() == default_info_copy.dump()

    info = PexInfo.default()
    info.code_hash = "foo"
    info.inherit_path = InheritPath.FALLBACK
    info.add_requirement("bar==1")
    info.add_requirement("baz==2")
    info.add_distribution("bar.whl", "bar-sha")
    info.add_distribution("baz.whl", "baz-sha")
    info.interpreter_constraints = InterpreterConstraints.parse(">=2.7.18", "CPython==2.7.9")
    info_copy = info.copy()

    assert "foo" == info_copy.code_hash
    assert InheritPath.FALLBACK == info_copy.inherit_path
    assert OrderedSet(["bar==1", "baz==2"]) == info_copy.requirements
    assert {"bar.whl": "bar-sha", "baz.whl": "baz-sha"} == info_copy.distributions
    assert (
        InterpreterConstraints.parse(">=2.7.18", "CPython==2.7.9")
        == info_copy.interpreter_constraints
    )
    assert info.dump() == info_copy.dump()
