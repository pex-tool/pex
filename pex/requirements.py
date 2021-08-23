# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import re
from contextlib import contextmanager

from pex import attrs, dist_metadata
from pex.compatibility import urlparse
from pex.dist_metadata import MetadataError, ProjectNameAndVersion
from pex.fetcher import URLFetcher
from pex.third_party.packaging.markers import Marker
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.packaging.version import InvalidVersion, Version
from pex.third_party.pkg_resources import Requirement, RequirementParseError
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import (
        Iterable,
        Iterator,
        Match,
        Optional,
        Text,
        Tuple,
        Union,
    )
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class LogicalLine(object):
    raw_text = attr.ib()  # type: Text
    processed_text = attr.ib()  # type: Text
    source = attr.ib()  # type: Text
    start_line = attr.ib()  # type: int
    end_line = attr.ib()  # type: int

    def render_location(self):
        # type: () -> str
        if self.start_line == self.end_line:
            return "{} line {}".format(self.source, self.start_line)
        return "{} lines {}-{}".format(self.source, self.start_line, self.end_line)


@attr.s(frozen=True)
class Source(object):
    @classmethod
    @contextmanager
    def from_url(
        cls,
        fetcher,  # type: URLFetcher
        url,  # type: Text
        is_constraints=False,  # type: bool
    ):
        # type: (...) -> Iterator[Source]
        with fetcher.get_body_iter(url) as lines:
            yield cls(origin=url, is_file=False, is_constraints=is_constraints, lines=lines)

    @classmethod
    @contextmanager
    def from_file(
        cls,
        path,  # type: Text
        is_constraints=False,  # type: bool
    ):
        # type: (...) -> Iterator[Source]
        realpath = os.path.realpath(path)
        with open(realpath) as fp:
            yield cls(origin=realpath, is_file=True, is_constraints=is_constraints, lines=fp)

    @classmethod
    def from_text(
        cls,
        contents,  # type: Text
        origin="<string>",  # type: Text
        is_constraints=False,  # type: bool
    ):
        # type: (...) -> Source
        return cls(
            origin=origin,
            is_file=False,
            is_constraints=is_constraints,
            lines=iter(contents.splitlines(True)),  # This is keepends=True.
        )

    origin = attr.ib()  # type: Text
    is_file = attr.ib()  # type: bool
    is_constraints = attr.ib()  # type: bool
    lines = attr.ib()  # type: Iterator[Text]

    @contextmanager
    def resolve(
        self,
        line,  # type: LogicalLine
        origin,  # type: Text
        is_constraints=False,  # type: bool
        fetcher=None,  # type: Optional[URLFetcher]
    ):
        # type: (...) -> Iterator[Source]
        def create_parse_error(msg):
            # type: (str) -> ParseError
            return ParseError(
                line,
                "Problem resolving {} file: {}".format(
                    "constraints" if is_constraints else "requirements", msg
                ),
            )

        url = urlparse.urlparse(urlparse.urljoin(self.origin, origin))
        if url.scheme and url.netloc:
            if fetcher is None:
                raise create_parse_error(
                    "The source is a url but no fetcher was supplied to resolve its contents with."
                )
            try:
                with self.from_url(fetcher, origin, is_constraints=is_constraints) as source:
                    yield source
            except OSError as e:
                raise create_parse_error(str(e))
            return

        path = url.path if url.scheme == "file" else origin
        try:
            with self.from_file(path, is_constraints=is_constraints) as source:
                yield source
        except (IOError, OSError) as e:
            raise create_parse_error(str(e))


@attr.s(frozen=True)
class PyPIRequirement(object):
    """A requirement realized through a package index or find links repository."""

    line = attr.ib()  # type: LogicalLine
    requirement = attr.ib()  # type: Requirement
    editable = attr.ib(default=False)  # type: bool


@attr.s(frozen=True)
class URLRequirement(object):
    """A requirement realized through an distribution archive at a fixed URL."""

    line = attr.ib()  # type: LogicalLine
    url = attr.ib()  # type: Text
    requirement = attr.ib()  # type: Requirement
    editable = attr.ib(default=False)  # type: bool


def parse_requirement_from_project_name_and_specifier(
    project_name,  # type: Text
    extras=None,  # type: Optional[Iterable[str]]
    specifier=None,  # type: Optional[SpecifierSet]
    marker=None,  # type: Optional[Marker]
):
    # type: (...) -> Requirement
    requirement_string = "{project_name}{extras}{specifier}".format(
        project_name=project_name,
        extras="[{extras}]".format(extras=", ".join(extras)) if extras else "",
        specifier=specifier or SpecifierSet(),
    )
    if marker:
        requirement_string += ";" + str(marker)
    return Requirement.parse(requirement_string)


def parse_requirement_from_dist(
    dist,  # type: str
    extras=None,  # type: Optional[Iterable[str]]
    marker=None,  # type: Optional[Marker]
):
    # type: (...) -> Requirement
    project_name_and_version = dist_metadata.project_name_and_version(dist)
    if project_name_and_version is None:
        raise ValueError(
            "Failed to find a project name and version from the given wheel path: "
            "{wheel}".format(wheel=dist)
        )
    project_name_and_specifier = ProjectNameAndSpecifier.from_project_name_and_version(
        project_name_and_version
    )
    return parse_requirement_from_project_name_and_specifier(
        project_name_and_specifier.project_name,
        extras=extras,
        specifier=project_name_and_specifier.specifier,
        marker=marker,
    )


@attr.s(frozen=True)
class LocalProjectRequirement(object):
    """A requirement realized by building a distribution from local sources."""

    line = attr.ib()  # type: LogicalLine
    path = attr.ib()  # type: str
    extras = attr.ib(default=(), converter=attrs.str_tuple_from_iterable)  # type: Tuple[str, ...]
    marker = attr.ib(default=None)  # type: Optional[Marker]
    editable = attr.ib(default=False)  # type: bool

    def as_requirement(self, dist):
        # type: (str) -> Requirement
        """Create a requirement given a distribution that was built from this local project."""
        return parse_requirement_from_dist(dist, self.extras, self.marker)


if TYPE_CHECKING:
    ParsedRequirement = Union[PyPIRequirement, URLRequirement, LocalProjectRequirement]


@attr.s(frozen=True)
class Constraint(object):
    line = attr.ib()  # type: LogicalLine
    requirement = attr.ib()  # type: Requirement


class ParseError(Exception):
    def __init__(
        self,
        logical_line,  # type: LogicalLine
        msg,  # type: str
    ):
        # type: (...) -> None
        super(ParseError, self).__init__(
            "{}:\n{}\n{}".format(logical_line.render_location(), logical_line.raw_text, msg)
        )
        self._logical_line = logical_line

    @property
    def logical_line(self):
        # type: () -> LogicalLine
        return self._logical_line


def _strip_requirement_options(line):
    # type: (LogicalLine) -> Tuple[bool, Text]

    processed_text = re.sub(r"^\s*(-e|--editable)\s+", "", line.processed_text)
    editable = processed_text != line.processed_text
    return editable, re.sub(r"\s--(global-option|install-option|hash).*$", "", processed_text)


def _is_recognized_non_local_pip_url_scheme(scheme):
    # type: (str) -> bool
    return bool(
        re.match(
            r"""
            (
                # Archives
                  ftp
                | https?

                # VCSs: https://pip.pypa.io/en/stable/reference/pip_install/#vcs-support
                | (
                      bzr
                    | git
                    | hg
                    | svn
                  )\+
            )
            """,
            scheme,
            re.VERBOSE,
        )
    )


@attr.s(frozen=True)
class ProjectNameExtrasAndMarker(object):
    project_name = attr.ib()  # type: Text
    extras = attr.ib(default=(), converter=attrs.str_tuple_from_iterable)  # type: Tuple[str, ...]
    marker = attr.ib(default=None)  # type: Optional[Marker]

    def astuple(self):
        # type: () -> Tuple[Text, Tuple[str, ...], Optional[Marker]]
        return self.project_name, self.extras, self.marker


def _try_parse_fragment_project_name_and_marker(fragment):
    # type: (Text) -> Optional[ProjectNameExtrasAndMarker]
    project_requirement = None
    for part in fragment.split("&"):
        if part.startswith("egg="):
            _, project_requirement = part.split("=", 1)
            break
    if project_requirement is None:
        return None
    try:
        req = Requirement.parse(project_requirement)
        return ProjectNameExtrasAndMarker(req.name, extras=req.extras, marker=req.marker)
    except (RequirementParseError, ValueError):
        return ProjectNameExtrasAndMarker(project_requirement)


@attr.s(frozen=True)
class ProjectNameAndSpecifier(object):
    @staticmethod
    def _version_as_specifier(version):
        # type: (str) -> SpecifierSet
        try:
            return SpecifierSet("=={}".format(Version(version)))
        except InvalidVersion:
            return SpecifierSet("==={}".format(version))

    @classmethod
    def from_project_name_and_version(cls, project_name_and_version):
        # type: (ProjectNameAndVersion) -> ProjectNameAndSpecifier
        return cls(
            project_name=project_name_and_version.project_name,
            specifier=cls._version_as_specifier(project_name_and_version.version),
        )

    project_name = attr.ib()  # type: Text
    specifier = attr.ib()  # type: SpecifierSet


def _try_parse_project_name_and_specifier_from_path(path):
    # type: (str) -> Optional[ProjectNameAndSpecifier]
    try:
        return ProjectNameAndSpecifier.from_project_name_and_version(
            ProjectNameAndVersion.from_filename(path)
        )
    except MetadataError:
        return None


def _try_parse_pip_local_formats(
    path,  # type: Text
    basepath=None,  # type: Optional[Text]
):
    # type: (...) -> Optional[ProjectNameExtrasAndMarker]
    project_requirement = os.path.basename(path)

    # Requirements strings can optionally include:
    REQUIREMENT_PARTS_START = (
        # + Trailing extras denoted by `[...]`.
        #   See: https://www.python.org/dev/peps/pep-0508/#extras
        r"\[",
        # + A version specifier denoted by a leading `!=`, `==`, `===`, `>=`, `<=` or `~=`.
        #   See: https://www.python.org/dev/peps/pep-0508/#grammar
        r"!=><~",
        # + Environment markers denoted by `;...`
        #   See: https://www.python.org/dev/peps/pep-0508/#environment-markers
        r";",
    )
    # N.B.: The basename of the current directory (.) is '' and we allow this.
    match = re.match(
        r"""
        ^
        (?P<directory_name>[^{REQUIREMENT_PARTS_START}]*)?
        (?P<requirement_parts>.*)?
        $
        """.format(
            REQUIREMENT_PARTS_START="".join(REQUIREMENT_PARTS_START)
        ),
        project_requirement,
        re.VERBOSE,
    )
    if not match:
        return None

    directory_name, requirement_parts = match.groups()
    stripped_path = os.path.join(os.path.dirname(path), directory_name)
    abs_stripped_path = (
        os.path.join(basepath, stripped_path) if basepath else os.path.abspath(stripped_path)
    )
    if not os.path.exists(abs_stripped_path):
        return None

    # Maybe a local archive or project path.
    requirement_parts = match.group("requirement_parts")
    if not requirement_parts:
        return ProjectNameExtrasAndMarker(abs_stripped_path)

    project_requirement = "fake_project{}".format(requirement_parts)
    try:
        req = Requirement.parse(project_requirement)
        return ProjectNameExtrasAndMarker(abs_stripped_path, extras=req.extras, marker=req.marker)
    except (RequirementParseError, ValueError):
        return None


def _split_direct_references(processed_text):
    # type: (Text) -> Union[Tuple[Text, Text], Tuple[None, None]]
    match = re.match(
        r"""
        ^
        (?P<requirement>[a-zA-Z0-9]+(?:[-_.]+[a-zA-Z0-9]+)*)
        \s*
        @
        \s*
        (?P<url>.+)?
        $
        """,
        processed_text,
        re.VERBOSE,
    )
    if not match:
        return None, None
    project_name, url = match.groups()
    return project_name, url


def _parse_requirement_line(
    line,  # type: LogicalLine
    basepath=None,  # type: Optional[Text]
):
    # type: (...) -> ParsedRequirement

    basepath = basepath or os.getcwd()

    editable, processed_text = _strip_requirement_options(line)
    project_name, direct_reference_url = _split_direct_references(processed_text)
    parsed_url = urlparse.urlparse(direct_reference_url or processed_text)

    # Handle non local URLs (Pip proprietary).
    if _is_recognized_non_local_pip_url_scheme(parsed_url.scheme):
        project_name_extras_and_marker = _try_parse_fragment_project_name_and_marker(
            parsed_url.fragment
        )
        project_name, extras, marker = (
            project_name_extras_and_marker.astuple()
            if project_name_extras_and_marker
            else (project_name, (), None)
        )
        specifier = None  # type: Optional[SpecifierSet]
        if not project_name:
            project_name_and_specifier = _try_parse_project_name_and_specifier_from_path(
                parsed_url.path
            )
            if project_name_and_specifier is not None:
                project_name = project_name_and_specifier.project_name
                specifier = project_name_and_specifier.specifier
        # Pip allows an environment marker after the url which matches the urlparse structure:
        #   scheme://netloc/path;parameters?query#fragment
        # See: https://docs.python.org/3/library/urllib.parse.html#urllib.parse.urlparse
        if not marker and parsed_url.params:
            marker = Marker(parsed_url.params)
        if project_name is None:
            raise ParseError(
                line,
                (
                    "Could not determine a project name for URL requirement {}, consider using "
                    "#egg=<project name>."
                ),
            )
        url = parsed_url._replace(params="", fragment="").geturl()
        requirement = parse_requirement_from_project_name_and_specifier(
            project_name,
            extras=extras,
            specifier=specifier,
            marker=marker,
        )
        return URLRequirement(line, url, requirement, editable=editable)

    # Handle local archives and project directories via path or file URL (Pip proprietary).
    local_requirement = parsed_url._replace(scheme="").geturl()
    project_name_extras_and_marker = _try_parse_pip_local_formats(
        local_requirement, basepath=basepath
    )
    maybe_abs_path, extras, marker = (
        project_name_extras_and_marker.astuple()
        if project_name_extras_and_marker
        else (project_name, (), None)
    )
    if isinstance(maybe_abs_path, str) and any(
        os.path.isfile(os.path.join(maybe_abs_path, *p))
        for p in ((), ("setup.py",), ("pyproject.toml",))
    ):
        archive_or_project_path = os.path.realpath(maybe_abs_path)
        if os.path.isdir(archive_or_project_path):
            return LocalProjectRequirement(
                line,
                archive_or_project_path,
                extras=extras,
                marker=marker,
                editable=editable,
            )
        try:
            requirement = parse_requirement_from_dist(
                archive_or_project_path, extras=extras, marker=marker
            )
            return URLRequirement(line, archive_or_project_path, requirement, editable=editable)
        except dist_metadata.UnrecognizedDistributionFormat:
            # This is not a recognized local archive distribution. Fall through and try parsing as a
            # PEP-440 requirement.
            pass

    # Handle PEP-440. See: https://www.python.org/dev/peps/pep-0440.
    #
    # The `pkg_resources.Requirement.parse` method does all of this for us (via
    # `packaging.requirements.Requirement`) except for the handling of PEP-440 direct url
    # references; which we handled above and won't encounter here.
    try:
        return PyPIRequirement(line, Requirement.parse(processed_text), editable=editable)
    except RequirementParseError as e:
        raise ParseError(
            line, "Problem parsing {!r} as a requirement: {}".format(processed_text, e)
        )


def _expand_env_var(line, match):
    # type: (LogicalLine, Match) -> Text
    env_var_name = match.group(1)
    value = os.environ.get(env_var_name)
    if value is None:
        raise ParseError(line, "No value for environment variable ${} is set.".format(env_var_name))
    return value


def _expand_env_vars(line):
    # type: (LogicalLine) -> Text
    # We afford for lowercase letters here over and above the spec.
    # See: https://pubs.opengroup.org/onlinepubs/007908799/xbd/envvar.html

    def expand_env_var(match):
        # type: (Match) -> Text
        return _expand_env_var(line, match)

    return re.sub(r"\${([A-Za-z0-9_]+)}", expand_env_var, line.processed_text)


def _get_parameter(line):
    # type: (LogicalLine) -> Text
    split_line = line.processed_text.split("=")
    if len(split_line) != 2:
        split_line = line.processed_text.split()
    if len(split_line) != 2:
        raise ParseError(line, "Unrecognized parameter format.")
    return split_line[1]


def parse_requirements(
    source,  # type: Source
    fetcher=None,  # type: Optional[URLFetcher]
):
    # type: (...) -> Iterator[Union[ParsedRequirement, Constraint]]

    # For the format specification, see:
    #   https://pip.pypa.io/en/stable/reference/pip_install/#requirements-file-format

    start_line = 0
    line_buffer = []
    logical_line_buffer = []

    for line_no, line in enumerate(source.lines, start=1):
        if start_line == 0:
            start_line = line_no
        line_buffer.append(line)
        stripped_line = line.strip()

        # Process line continuations first.
        if re.search(r"(^|[^\\])\\$", stripped_line):
            logical_line_buffer.append(stripped_line[:-1])
            continue

        end_line = line_no
        logical_line_buffer.append(stripped_line)

        # Strip comment lines and trailing comments from non-comment lines.
        logical_line_stripped = re.sub(r"(^|\s+)#.*$", "", "".join(logical_line_buffer))
        logical_line = LogicalLine(
            raw_text="".join(line_buffer),
            processed_text=logical_line_stripped,
            source=source.origin,
            start_line=start_line,
            end_line=end_line,
        )
        logical_line = attr.evolve(logical_line, processed_text=_expand_env_vars(logical_line))
        try:
            # Recurse on any other requirement or constraint files.
            processed_text = logical_line.processed_text
            requirement_file = processed_text.startswith(("-r", "--requirement"))
            constraint_file = not requirement_file and processed_text.startswith(
                ("-c", "--constraint")
            )
            if requirement_file or constraint_file:
                relpath = _get_parameter(logical_line)
                with source.resolve(
                    line=logical_line,
                    origin=relpath,
                    is_constraints=constraint_file,
                    fetcher=fetcher,
                ) as other_source:
                    for requirement in parse_requirements(other_source, fetcher=fetcher):
                        yield requirement
                continue

            # Skip empty lines, comment lines and all other Pip options.
            if not processed_text or processed_text.startswith("-"):
                continue

            # Only requirement lines remain.
            requirement = _parse_requirement_line(
                logical_line, basepath=os.path.dirname(source.origin) if source.is_file else None
            )
            if source.is_constraints:
                if not isinstance(requirement, PyPIRequirement) or requirement.requirement.extras:
                    raise ParseError(
                        logical_line,
                        "Constraint files do not support VCS, URL or local project requirements"
                        "and they do not support requirements with extras. Search for 'We are also "
                        "changing our support for Constraints Files' here: "
                        "https://pip.pypa.io/en/stable/user_guide/"
                        "#changes-to-the-pip-dependency-resolver-in-20-3-2020.",
                    )
                yield Constraint(logical_line, requirement.requirement)
            else:
                yield requirement
        finally:
            start_line = 0
            del line_buffer[:]
            del logical_line_buffer[:]


def parse_requirement_file(
    location,  # type: Text
    is_constraints=False,  # type: bool
    fetcher=None,  # type: Optional[URLFetcher]
):
    # type: (...) -> Iterator[Union[ParsedRequirement, Constraint]]
    def open_source():
        url = urlparse.urlparse(location)
        if url.scheme and url.netloc:
            if fetcher is None:
                raise ValueError(
                    "The location is a url but no fetcher was supplied to resolve its contents "
                    "with."
                )
            return Source.from_url(fetcher=fetcher, url=location, is_constraints=is_constraints)

        path = url.path if url.scheme == "file" else location
        return Source.from_file(path=path, is_constraints=is_constraints)

    with open_source() as source:
        for req_info in parse_requirements(source, fetcher=fetcher):
            yield req_info


def parse_requirement_strings(requirements):
    # type: (Iterable[Text]) -> Iterator[ParsedRequirement]
    for requirement in requirements:
        yield _parse_requirement_line(
            LogicalLine(
                raw_text=requirement,
                processed_text=requirement.strip(),
                source="<string>",
                start_line=1,
                end_line=1,
            )
        )
