# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import warnings

import pytest

from pex.common import temporary_dir
from pex.pex_warnings import PEXWarning
from pex.testing import environment_as
from pex.typing import TYPE_CHECKING
from pex.util import named_temporary_file
from pex.variables import NoValueError, Variables

if TYPE_CHECKING:
    from typing import Any


def test_process_pydoc():
    # type: () -> None
    def thing():
        # no pydoc
        pass

    assert Variables.process_pydoc(thing.__doc__) == ("Unknown", "Unknown")

    def other_thing():
        """Type

        Properly
                formatted
            text.
        """

    assert Variables.process_pydoc(other_thing.__doc__) == ("Type", "Properly formatted text.")


def test_iter_help():
    # type: () -> None
    for variable_name, variable_type, variable_text in Variables.iter_help():
        assert variable_name.startswith("PEX_")
        assert "\n" not in variable_type
        assert "\n" not in variable_text


def test_pex_bool_variables():
    # type: () -> None
    assert Variables(environ={})._maybe_get_bool("NOT_HERE") is None
    with pytest.raises(NoValueError):
        Variables(environ={})._get_bool("NOT_HERE")

    for value in ("0", "faLsE", "false"):
        assert Variables(environ={"HERE": value})._get_bool("HERE") is False
    for value in ("1", "TrUe", "true"):
        assert Variables(environ={"HERE": value})._get_bool("HERE") is True
    with pytest.raises(SystemExit):
        Variables(environ={"HERE": "garbage"})._get_bool("HERE")

    # end to end
    assert Variables().PEX_ALWAYS_CACHE is False
    assert Variables({"PEX_ALWAYS_CACHE": "1"}).PEX_ALWAYS_CACHE is True


def test_pex_string_variables():
    # type: () -> None
    assert Variables(environ={})._maybe_get_string("NOT_HERE") is None
    with pytest.raises(NoValueError):
        Variables(environ={})._get_string("NOT_HERE")
    assert Variables(environ={"HERE": "stuff"})._get_string("HERE") == "stuff"


def test_pex_get_int():
    # type: () -> None
    with pytest.raises(NoValueError):
        Variables()._get_int("HELLO")
    assert Variables(environ={"HELLO": "23"})._get_int("HELLO") == 23
    with pytest.raises(SystemExit):
        assert Variables(environ={"HELLO": "welp"})._get_int("HELLO")


def assert_pex_vars_hermetic():
    # type: () -> None
    v = Variables()
    assert os.environ.copy() == v.copy()

    existing = os.environ.get("TEST")
    expected = (existing or "") + "different"
    assert expected != existing

    with environment_as(TEST=expected):
        assert expected != v.copy().get("TEST")


def test_pex_vars_hermetic_no_pexrc():
    # type: () -> None
    assert_pex_vars_hermetic()


def test_pex_vars_hermetic():
    # type: () -> None
    with environment_as(PEX_IGNORE_RCFILES="True"):
        assert_pex_vars_hermetic()


def test_pex_get_kv():
    # type: () -> None
    v = Variables(environ={})
    assert v._get_kv("HELLO") is None
    assert v._get_kv("=42") is None
    assert v._get_kv("TOO=MANY=COOKS") is None
    assert v._get_kv("THIS=WORKS") == ["THIS", "WORKS"]


def test_pex_from_rc():
    # type: () -> None
    with named_temporary_file(mode="w") as pexrc:
        pexrc.write("HELLO=42")
        pexrc.flush()
        v = Variables(rc=pexrc.name)
        assert v._get_int("HELLO") == 42


def test_pexrc_precedence():
    # type: () -> None
    with named_temporary_file(mode="w") as pexrc:
        pexrc.write("HELLO=FORTYTWO")
        pexrc.flush()
        v = Variables(rc=pexrc.name, environ={"HELLO": "42"})
        assert v._get_int("HELLO") == 42


def test_rc_ignore():
    # type: () -> None
    with named_temporary_file(mode="w") as pexrc:
        pexrc.write("HELLO=FORTYTWO")
        pexrc.flush()
        v = Variables(rc=pexrc.name, environ={"PEX_IGNORE_RCFILES": "True"})
        assert "HELLO" not in v._environ


def test_pex_vars_defaults_stripped():
    # type: () -> None
    v = Variables(environ={})

    # bool
    assert v.PEX_ALWAYS_CACHE is not None
    assert Variables.PEX_ALWAYS_CACHE.strip_default(v) is None

    # string
    assert v.PEX_PATH is not None
    assert Variables.PEX_PATH.strip_default(v) is None

    # int
    assert v.PEX_VERBOSE is not None
    assert Variables.PEX_VERBOSE.strip_default(v) is None


def test_pex_root_unwriteable():
    # type: () -> None
    with temporary_dir() as td:
        pex_root = os.path.realpath(os.path.join(td, "pex_root"))
        os.mkdir(pex_root, 0o444)

        env = Variables(environ=dict(PEX_ROOT=pex_root))

        with warnings.catch_warnings(record=True) as log:
            assert pex_root != env.PEX_ROOT

        assert 1 == len(log)
        message = log[0].message
        assert isinstance(message, PEXWarning)
        assert pex_root in str(message)
        assert env.PEX_ROOT is not None
        assert env.PEX_ROOT in str(message)

        assert (
            env.PEX_ROOT == env.PEX_ROOT
        ), "When an ephemeral PEX_ROOT is materialized it should be stable."


def test_pex_vars_value_or(tmpdir):
    # type: (Any) -> None
    v = Variables(environ={})

    assert v.PEX_ROOT is not None, "Expected PEX_ROOT to be a defaulted variable."

    pex_root = str(tmpdir)
    assert pex_root == Variables.PEX_ROOT.value_or(v, pex_root)

    unwriteable_pex_root = os.path.join(pex_root, "unwriteable")
    os.mkdir(unwriteable_pex_root, 0o444)
    assert unwriteable_pex_root != Variables.PEX_ROOT.value_or(v, unwriteable_pex_root), (
        "Expected the fallback to be validated, and in the case of PEX_ROOT, replaced with a "
        "writeable tmp dir"
    )
