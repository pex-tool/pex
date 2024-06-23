# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import re
from textwrap import dedent

import pytest

from pex.dist_metadata import Requirement
from pex.pep_723 import ScriptMetadata
from pex.third_party.packaging import specifiers


def test_parse_empty():
    # type: () -> None

    assert not ScriptMetadata.parse("")
    assert not ScriptMetadata.parse(
        dedent(
            """\
            # /// script
            # ///
            """
        )
    )
    assert not ScriptMetadata.parse(
        dedent(
            """\
            # /// script
            # unknown_key = 42
            # ///
            """
        )
    )
    assert not ScriptMetadata.parse(
        dedent(
            """\
            # /// script
            # unknown_key = 42
            # ///
            # dependencies = ["ansicolors"]
            """
        )
    )


def test_parse_unterminated():
    # type: () -> None

    assert not ScriptMetadata.parse(
        dedent(
            """\
            # /// script
            # dependencies = ["ansicolors"]

            # # N.B.: The line above does not start with # which should terminate the search for
            # # the terminator immediately below.
            # ///
            """
        )
    )
    assert not ScriptMetadata.parse(
        dedent(
            """\
            # /// script
            # dependencies = ["ansicolors"]
            """
        )
    )


def test_parse_greedy():
    # type: () -> None

    with pytest.raises(
        specifiers.InvalidSpecifier,
        match=re.escape(
            "Invalid specifier: 'Invalid specifier with embedded script metadata block trojan.\n"
            "///'"
        ),
    ):
        ScriptMetadata.parse(
            dedent(
                '''\
                # /// script
                # requires-python = """
                # Invalid specifier with embedded script metadata block trojan.
                # ///
                # """
                # ///
                '''
            )
        )


def test_parse_nominal():
    assert ScriptMetadata(
        dependencies=tuple([Requirement.parse("ansicolors")])
    ) == ScriptMetadata.parse(
        dedent(
            """
            # /// script
            # dependencies = ["ansicolors"]
            # ///
            """
        )
    )

    assert ScriptMetadata(requires_python=specifiers.SpecifierSet("~=3.8")) == ScriptMetadata.parse(
        dedent(
            """
            # /// script
            # requires-python = "~=3.8"
            # ///
            """
        )
    )

    assert ScriptMetadata(
        dependencies=tuple([Requirement.parse("cowsay<6")]),
        requires_python=specifiers.SpecifierSet("==2.7.*"),
    ) == ScriptMetadata.parse(
        dedent(
            """
            dependencies = ["before"]
            # /// script
            # dependencies = [
            #   "cowsay<6",
            # ]
            #
            # # Yup, 2.7.
            # requires-python = "==2.7.*"
            #
            # not-a-recognized-key = 42
            # ///
            dependencies = ["after"]
            """
        )
    )
