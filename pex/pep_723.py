# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import ast
import re
from collections import OrderedDict, defaultdict

from pex import toml
from pex.common import pluralize
from pex.compatibility import string
from pex.dist_metadata import Requirement, RequirementParseError
from pex.third_party.packaging.specifiers import InvalidSpecifier, SpecifierSet
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, DefaultDict, List, Mapping, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


_UNSPECIFIED_SOURCE = "<unspecified source>"
_SPEC_URL = (
    "https://packaging.python.org/specifications/inline-script-metadata#inline-script-metadata"
)


class InvalidMetadataError(ValueError):
    """Indicates invalid PEP-723 script metadata."""


@attr.s(frozen=True)
class MetadataBlock(object):
    source = attr.ib()  # type: str
    start_line = attr.ib()  # type: int
    type = attr.ib()  # type: str
    content = attr.ib()  # type: Tuple[str, ...]

    def create_metadata_error(self, problem_clause):
        # type: (str) -> InvalidMetadataError
        return InvalidMetadataError(
            "The script metadata found in {source} starting at line {line} {problem_clause}.\n"
            "See: {spec_url}".format(
                source=self.source,
                line=self.start_line,
                problem_clause=problem_clause,
                spec_url=_SPEC_URL,
            )
        )

    def parse_metadata(self):
        # type: () -> Mapping[str, Any]
        stripped_content = "\n".join(
            line[2:] if line.startswith("# ") else line[1:] for line in self.content
        )
        try:
            return cast("Mapping[str, Any]", toml.loads(stripped_content))
        except toml.TomlDecodeError as e:
            raise self.create_metadata_error("embeds malformed toml: {err}".format(err=e))


@attr.s
class ParseState(object):
    start_type = attr.ib(default="", init=False)  # type: str
    start_line = attr.ib(default=0, init=False)  # type: int
    end_line = attr.ib(default=0, init=False)  # type: int

    def reset(
        self,
        start_type="",  # type: str
        start_line=0,  # type: int
    ):
        # type: (...) -> None
        self.start_type = start_type
        self.start_line = start_line
        self.end_line = 0

    @property
    def started(self):
        # type: () -> bool
        return bool(self.start_type) and self.start_line > 0

    @property
    def finished(self):
        # type: () -> bool
        return self.started and self.end_line >= self.start_line


@attr.s(frozen=True)
class Code(object):
    @classmethod
    def parse(
        cls,
        code,  # type: str
        line_count=None,  # type: Optional[int]
    ):
        # type: (...) -> Code

        lines = defaultdict(lambda: True)  # type: DefaultDict[int, bool]
        root = None  # type: Optional[ast.AST]
        try:
            root = ast.parse(code)
        except SyntaxError as e:
            TRACER.log(
                "Cannot parse script code for robust PEP-723 analysis, continuing with naive "
                "analysis: {err}".format(err=e),
            )
        if root:
            for node in ast.walk(root):
                start_line = getattr(node, "lineno", 0)
                if start_line:
                    end_line = getattr(node, "end_lineno", 0)
                    # For Python<3.8 multiline string literals were represented in Str nodes with
                    # the lineno being the _last_ line of the string literal. We calculate the first
                    # line number by subtracting the height of the multiline text block.
                    if not end_line and node.__class__.__name__ == "Str":
                        line_count = len(getattr(node, "s", "").splitlines())
                        if line_count > 1:
                            end_line = start_line
                            start_line = end_line - len(getattr(node, "s", "").splitlines())
                    if end_line > start_line:
                        for offset in range(end_line - start_line):
                            lines[start_line + offset - 1] = False
                    else:
                        lines[start_line - 1] = False

        return cls(lines)

    # True marks a whitespace or comment line. Everything else is code.
    lines = attr.ib()  # type: DefaultDict[int, bool]

    def is_comment(self, line_no):
        # type: (int) -> bool
        return self.lines[line_no - 1]


def parse_metadata_blocks(
    script,  # type: str
    source=_UNSPECIFIED_SOURCE,  # type: str
):
    # type: (...) -> Mapping[str, MetadataBlock]

    lines = script.splitlines()
    code = Code.parse(script, line_count=len(lines))

    metadata_blocks = OrderedDict()  # type: OrderedDict[str, List[MetadataBlock]]
    parse_state = ParseState()

    def add_metadata_block():
        # type: () -> None
        metadata_blocks.setdefault(parse_state.start_type, []).append(
            MetadataBlock(
                source=source,
                start_line=parse_state.start_line,
                type=parse_state.start_type,
                content=tuple(lines[parse_state.start_line : parse_state.end_line - 1]),
            )
        )
        parse_state.reset()

    for line_no, line in enumerate(lines, start=1):
        start = re.match(r"^# /// (?P<type>[a-zA-Z0-9-]+)$", line)
        is_comment = code.is_comment(line_no)
        if start and is_comment and parse_state.started and not parse_state.finished:
            raise InvalidMetadataError(
                "The script metadata found in {source} contains a `# /// {outer_type}` block "
                "beginning on line {outer_start_line} that is followed by a `# /// {inner_type}` "
                "block beginning on line {inner_start_line} before the {outer_type!r} block "
                "starting on line {outer_start_line} is closed.\n"
                "Metadata blocks must be closed before a new metadata block can begin.\n"
                "See: {spec_url}".format(
                    source=source,
                    outer_type=parse_state.start_type,
                    outer_start_line=parse_state.start_line,
                    inner_type=start.group("type"),
                    inner_start_line=line_no,
                    spec_url=_SPEC_URL,
                )
            )
        elif start and is_comment:
            if parse_state.finished:
                add_metadata_block()
            parse_state.reset(start_type=start.group("type"), start_line=line_no)
        elif parse_state.started and is_comment and "# ///" == line:
            parse_state.end_line = line_no
        elif not is_comment or (line != "#" and not line.startswith("# ")):
            if parse_state.finished and parse_state.end_line == line_no - 1:
                add_metadata_block()
            else:
                parse_state.reset()
    if parse_state.finished:
        add_metadata_block()

    over_abundant_blocks = []  # type: List[str]
    for type_, blocks in metadata_blocks.items():
        count = len(blocks)
        if count > 1:
            over_abundant_blocks.append(
                "+ {count} `# /// {type}` metadata blocks beginning on lines {lines}.".format(
                    count=count,
                    type=type_,
                    lines="{lines} and {last_line}".format(
                        lines=", ".join(map(str, (block.start_line for block in blocks[:-1]))),
                        last_line=blocks[-1].start_line,
                    ),
                )
            )

    if over_abundant_blocks:
        raise InvalidMetadataError(
            "Found {count} metadata block {types} in {source} with more than one appearance:\n"
            "{over_abundant_blocks}\n"
            "At most one metadata block of each type is allowed.\n"
            "See: {spec_url}".format(
                count=len(over_abundant_blocks),
                types=pluralize(over_abundant_blocks, "type"),
                source=source,
                over_abundant_blocks="\n".join(over_abundant_blocks),
                spec_url=_SPEC_URL,
            )
        )
    return {type_: blocks[0] for type_, blocks in metadata_blocks.items()}


@attr.s(frozen=True)
class ScriptMetadata(object):
    @classmethod
    def parse(
        cls,
        script,  # type: str
        source=_UNSPECIFIED_SOURCE,  # type: str
    ):
        # type: (...) -> ScriptMetadata

        # The spec this code follows was defined in PEP-723: https://peps.python.org/pep-0723/
        # and now lives here:
        # https://packaging.python.org/specifications/inline-script-metadata#inline-script-metadata
        script_metadata_block = parse_metadata_blocks(script, source=source).get("script")
        if not script_metadata_block:
            return cls()
        script_metadata = script_metadata_block.parse_metadata()

        raw_dependencies = script_metadata.get("dependencies", [])
        if not isinstance(raw_dependencies, list):
            raise script_metadata_block.create_metadata_error(
                "contains an invalid `dependencies` value of type `{type}`\n"
                "Expected a list of dependency specifier strings".format(
                    type=type(raw_dependencies).__name__
                )
            )

        invalid_dependencies = []  # type: List[str]
        dependencies = []  # type: List[Requirement]
        for index, req in enumerate(raw_dependencies):
            try:
                dependencies.append(Requirement.parse(req))
            except RequirementParseError as e:
                invalid_dependencies.append(
                    "+ dependencies[{index}] {req!r}: {err}".format(index=index, req=req, err=e)
                )
        if invalid_dependencies:
            raise script_metadata_block.create_metadata_error(
                "contains a `dependencies` list with {count} invalid dependency {specifiers}:\n"
                "{invalid_dependencies}".format(
                    count=len(invalid_dependencies),
                    specifiers=pluralize(invalid_dependencies, "specifier"),
                    invalid_dependencies="\n".join(invalid_dependencies),
                )
            )

        raw_requires_python = script_metadata.get("requires-python", "")
        if not isinstance(raw_requires_python, string):
            raise script_metadata_block.create_metadata_error(
                "contains an invalid `requires-python` value of type `{type}`\n"
                "Expected a version specifier string".format(
                    type=type(raw_requires_python).__name__
                )
            )
        try:
            requires_python = SpecifierSet(raw_requires_python)
        except InvalidSpecifier as e:
            raise script_metadata_block.create_metadata_error(
                "contains an invalid `requires-python` value {value!r}: {err}".format(
                    value=raw_requires_python, err=e
                )
            )

        return cls(dependencies=tuple(dependencies), requires_python=requires_python, source=source)

    dependencies = attr.ib(default=())  # type: Tuple[Requirement, ...]
    requires_python = attr.ib(default=SpecifierSet())  # type: SpecifierSet
    source = attr.ib(default=_UNSPECIFIED_SOURCE)  # type: str

    def __bool__(self):
        # type: () -> bool
        return bool(self.dependencies) or bool(self.requires_python)

    # N.B.: For Python 2.7.
    __nonzero__ = __bool__
