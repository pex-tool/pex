# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import re
import sys
from textwrap import dedent

import pytest

from pex.dist_metadata import Requirement
from pex.pep_723 import InvalidMetadataError, ScriptMetadata
from pex.third_party.packaging import specifiers
from testing import PY_VER


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
        InvalidMetadataError,
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
    # type: () -> None

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


def test_parse_invalid_embedded_start():
    # type: () -> None

    with pytest.raises(
        InvalidMetadataError,
        match=re.escape(
            "The script metadata found in <unspecified source> contains a `# /// script` block "
            "beginning on line 1 that is followed by a `# /// script` block beginning on line 2 "
            "before the 'script' block starting on line 1 is closed.\n"
            "Metadata blocks must be closed before a new metadata block can begin.\n"
            "See: https://packaging.python.org/specifications/"
            "inline-script-metadata#inline-script-metadata"
        ),
    ):
        ScriptMetadata.parse(
            dedent(
                """\
                # /// script
                # /// script
                # ///
                """
            )
        )

    with pytest.raises(
        InvalidMetadataError,
        match=re.escape(
            "The script metadata found in <unspecified source> contains a `# /// script` block "
            "beginning on line 3 that is followed by a `# /// future` block beginning on line 5 "
            "before the 'script' block starting on line 3 is closed.\n"
            "Metadata blocks must be closed before a new metadata block can begin.\n"
            "See: https://packaging.python.org/specifications/"
            "inline-script-metadata#inline-script-metadata"
        ),
    ):
        ScriptMetadata.parse(
            dedent(
                """\
                # Preamble.
                #
                # /// script
                #
                # /// future
                # ///
                """
            )
        )


def test_parse_invalid_multiple_blocks():
    # type: () -> None

    with pytest.raises(
        InvalidMetadataError,
        match=re.escape(
            "Found 2 metadata block types in <unspecified source> with more than one appearance:\n"
            "+ 2 `# /// script` metadata blocks beginning on lines 3 and 8.\n"
            "+ 3 `# /// future` metadata blocks beginning on lines 6, 11 and 15.\n"
            "At most one metadata block of each type is allowed.\n"
            "See: https://packaging.python.org/specifications/"
            "inline-script-metadata#inline-script-metadata"
        ),
    ):
        ScriptMetadata.parse(
            dedent(
                """\
                # A script that uses PEP-723, badly.
                #
                # /// script
                # ///

                # /// future
                # ///
                # /// script
                # ///
                #
                # /// future
                # ///
                # /// bob
                # ///
                # /// future
                # ///
                """
            )
        )


def test_parse_invalid_toml():
    # type: () -> None

    with pytest.raises(
        InvalidMetadataError,
        match=re.escape(
            "The script metadata found in exe.py starting at line 3 embeds malformed toml: "
            "{toml_error}.\n"
            "See: https://packaging.python.org/specifications/"
            "inline-script-metadata#inline-script-metadata".format(
                toml_error=(
                    "Invalid value (at line 1, column 21)"  # N.B.: tomli
                    if sys.version_info[:2] >= (3, 7)
                    else "Empty value is invalid (line 1 column 1 char 0)"  # N.B.: toml
                )
            )
        ),
    ):
        ScriptMetadata.parse(
            dedent(
                """\
                # Preamble.
                #
                # /// script
                # unspecified_value = # These are invalid in TOML; you must specify a value.
                # ///
                """
            ),
            source="exe.py",
        )


def test_parse_invalid_dependencies_value_type():
    # type: () -> None

    with pytest.raises(
        InvalidMetadataError,
        match=re.escape(
            "The script metadata found in <unspecified source> starting at line 1 contains an "
            "invalid `dependencies` value of type `int`\n"
            "Expected a list of dependency specifier strings.\n"
            "See: https://packaging.python.org/specifications/"
            "inline-script-metadata#inline-script-metadata"
        ),
    ):
        ScriptMetadata.parse(
            dedent(
                """\
                # /// script
                # dependencies = 42
                # ///
                """
            )
        )


@pytest.mark.skipif(
    PY_VER < (3, 7),
    reason=(
        "The version of vendored packaging used for Python>=3.7 is required for the precise error "
        "message being tested against."
    ),
)
def test_parse_invalid_dependencies_values():
    # type: () -> None

    with pytest.raises(
        InvalidMetadataError,
        match=re.escape(
            "The script metadata found in <unspecified source> starting at line 1 contains a "
            "`dependencies` list with 2 invalid dependency specifiers:\n"
            "+ dependencies[1] '; python_version >= \"3.8\"': Expected package name at the "
            "start of dependency specifier\n"
            '    ; python_version >= "3.8"\n'
            "    ^\n"
            "+ dependencies[3] '|': Expected package name at the start of dependency specifier\n"
            "    |\n"
            "    ^.\n"
            "See: https://packaging.python.org/specifications/"
            "inline-script-metadata#inline-script-metadata"
        ),
    ):
        ScriptMetadata.parse(
            dedent(
                """\
                # /// script
                # dependencies = [
                #     "ansicolors",
                #     "; python_version >= \\"3.8\\"",
                #     "cowsay",
                #     "|",
                # ]
                # ///
                """
            )
        )


def test_parse_invalid_requires_python_value_type():
    # type: () -> None

    with pytest.raises(
        InvalidMetadataError,
        match=re.escape(
            "The script metadata found in <unspecified source> starting at line 1 contains an "
            "invalid `requires-python` value of type `int`\n"
            "Expected a version specifier string.\n"
            "See: https://packaging.python.org/specifications/"
            "inline-script-metadata#inline-script-metadata"
        ),
    ):
        ScriptMetadata.parse(
            dedent(
                """\
                # /// script
                # requires-python = 42
                # ///
                """
            )
        )


@pytest.mark.skipif(
    PY_VER < (3, 7),
    reason=(
        "The version of vendored packaging used for Python>=3.7 is required for the precise error "
        "message being tested against."
    ),
)
def test_parse_invalid_requires_python_value():
    # type: () -> None

    with pytest.raises(
        InvalidMetadataError,
        match=re.escape(
            "The script metadata found in <unspecified source> starting at line 1 contains an "
            "invalid `requires-python` value '>=3.8.*': Invalid specifier: '>=3.8.*'.\n"
            "See: https://packaging.python.org/specifications/"
            "inline-script-metadata#inline-script-metadata"
        ),
    ):
        ScriptMetadata.parse(
            dedent(
                """\
                # /// script
                # requires-python = ">=3.8.*"
                # ///
                """
            )
        )
