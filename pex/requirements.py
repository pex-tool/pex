# Copyright 2015 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import re
import shlex
import sys
from argparse import ArgumentParser
from contextlib import contextmanager

from pex import attrs, dist_metadata, pex_warnings
from pex.artifact_url import VCS, ArtifactURL, VCSScheme, parse_qs
from pex.compatibility import url_quote, urlparse
from pex.dist_metadata import (
    ProjectNameAndVersion,
    Requirement,
    RequirementParseError,
    UnrecognizedDistributionFormat,
)
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.third_party.packaging.markers import Marker
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.packaging.version import InvalidVersion, Version
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import FrozenSet, Iterable, Iterator, Match, Optional, Text, Tuple, Union

    import attr  # vendor:skip

    from pex.fetcher import URLFetcher
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class LogicalLine(object):
    @classmethod
    def from_str(
        cls,
        text,  # type: Text
        source="<string>",  # type: Text
    ):
        # type: (...) -> LogicalLine
        return LogicalLine(
            raw_text=text,
            processed_text=text.strip(),
            source=source,
            start_line=1,
            end_line=1,
        )

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
        pex_warnings.warn(
            "Fetching {subject} files via url is deprecated: {url}".format(
                url=url, subject="constraints" if is_constraints else "requirements"
            )
        )
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
        if not os.path.isabs(path) and self.is_file:
            path = os.path.join(os.path.dirname(self.origin), path)
        try:
            with self.from_file(path, is_constraints=is_constraints) as source:
                yield source
        except (IOError, OSError) as e:
            raise create_parse_error(str(e))


@attr.s(frozen=True)
class _ParsedItem(object):
    line = attr.ib()  # type: LogicalLine

    def __str__(self):
        # type: () -> str
        return str(self.line.processed_text)


@attr.s(frozen=True)
class _Repo(_ParsedItem):
    location = attr.ib()  # Text


@attr.s(frozen=True)
class FindLinks(_Repo):
    pass


@attr.s(frozen=True)
class Index(_Repo):
    pass


@attr.s(frozen=True)
class PyPIRequirement(_ParsedItem):
    """A requirement realized through a package index or find links repository."""

    requirement = attr.ib()  # type: Requirement

    @property
    def project_name(self):
        # type: () -> ProjectName
        return self.requirement.project_name

    @property
    def extras(self):
        # type: () -> FrozenSet[str]
        return self.requirement.extras

    @property
    def marker(self):
        # type: () -> Optional[Marker]
        return self.requirement.marker


@attr.s(frozen=True)
class URLRequirement(_ParsedItem):
    """A requirement realized through a distribution archive at a fixed URL."""

    url = attr.ib()  # type: ArtifactURL
    requirement = attr.ib()  # type: Requirement

    @property
    def project_name(self):
        # type: () -> ProjectName
        return self.requirement.project_name

    @property
    def extras(self):
        # type: () -> FrozenSet[str]
        return self.requirement.extras

    @property
    def marker(self):
        # type: () -> Optional[Marker]
        return self.requirement.marker

    @property
    def filename(self):
        # type: () -> str
        return os.path.basename(self.url.path)

    @property
    def subdirectory(self):
        # type: () -> Optional[str]
        subdirectories = self.url.fragment_parameters.get("subdirectory")
        return subdirectories[-1] if subdirectories else None


@attr.s(frozen=True)
class VCSRequirement(_ParsedItem):
    """A requirement realized by building a distribution from sources retrieved from a VCS."""

    vcs = attr.ib()  # type: VCS.Value
    url = attr.ib()  # type: Text
    requirement = attr.ib()  # type: Requirement
    commit = attr.ib(default=None)  # type: Optional[str]

    @property
    def project_name(self):
        # type: () -> ProjectName
        return self.requirement.project_name

    @property
    def extras(self):
        # type: () -> FrozenSet[str]
        return self.requirement.extras

    @property
    def marker(self):
        # type: () -> Optional[Marker]
        return self.requirement.marker


def requirement_from_parts(
    project_name,  # type: Text
    extras=None,  # type: Optional[Iterable[str]]
    specifier=None,  # type: Optional[SpecifierSet]
    marker=None,  # type: Optional[Marker]
    editable=False,  # type: bool
    url=None,  # type: Optional[Text]
):
    # type: (...) -> Requirement
    requirement_string = "{project_name}{extras}{specifier}".format(
        project_name=project_name,
        extras="[{extras}]".format(extras=", ".join(extras)) if extras else "",
        specifier=specifier or SpecifierSet(),
    )
    if marker:
        requirement_string += ";" + str(marker)
    return attr.evolve(Requirement.parse(requirement_string, editable=editable), url=url)


@attr.s(frozen=True)
class LocalProjectRequirement(_ParsedItem):
    """A requirement realized by building a distribution from local sources."""

    path = attr.ib()  # type: str
    extras = attr.ib(default=(), converter=attrs.str_tuple_from_iterable)  # type: Tuple[str, ...]
    marker = attr.ib(default=None)  # type: Optional[Marker]
    editable = attr.ib(default=False)  # type: bool
    project_name = attr.ib(default=None)  # type: Optional[ProjectName]

    def as_requirement(self, dist=None):
        # type: (Optional[str]) -> Requirement
        """Create a requirement given a distribution that was built from this local project."""

        specifier = None  # type: Optional[SpecifierSet]
        url = None  # type: Optional[Text]
        if dist is not None:
            project_name_and_version = dist_metadata.project_name_and_version(dist)
            if project_name_and_version is None:
                raise ValueError(
                    "Failed to find a project name and version from the given distribution path: "
                    "{dist}".format(dist=dist)
                )
            project_name_and_specifier = _ProjectNameAndSpecifier.from_project_name_and_version(
                project_name_and_version
            )
            project_name = project_name_and_specifier.project_name
            specifier = project_name_and_specifier.specifier
        elif self.project_name is not None:
            project_name = self.project_name.raw
            url = "file://{path}".format(path=self.path)
        else:
            raise ValueError(
                "No distribution was supplied and the local project at {path} has an unknown "
                "project name; so no requirement can be calculated.".format(path=self.path)
            )

        return requirement_from_parts(
            project_name=project_name,
            extras=self.extras,
            specifier=specifier,
            marker=self.marker,
            editable=self.editable,
            url=url,
        )


if TYPE_CHECKING:
    ParsedRequirement = Union[
        PyPIRequirement, URLRequirement, VCSRequirement, LocalProjectRequirement
    ]


@attr.s(frozen=True)
class Constraint(_ParsedItem):
    requirement = attr.ib()  # type: Requirement

    @property
    def project_name(self):
        return self.requirement.project_name

    @property
    def marker(self):
        # type: () -> Optional[Marker]
        return self.requirement.marker


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


@attr.s(frozen=True)
class _ProjectNameAndSpecifier(object):
    @staticmethod
    def _version_as_specifier(version):
        # type: (Text) -> SpecifierSet
        try:
            return SpecifierSet("=={}".format(Version(version)))
        except InvalidVersion:
            return SpecifierSet("==={}".format(version))

    @classmethod
    def from_project_name_and_version(cls, project_name_and_version):
        # type: (ProjectNameAndVersion) -> _ProjectNameAndSpecifier
        return cls(
            project_name=project_name_and_version.project_name,
            specifier=cls._version_as_specifier(project_name_and_version.version),
        )

    project_name = attr.ib()  # type: Text
    specifier = attr.ib()  # type: SpecifierSet


def _parse_url(
    raw_url,  # type: Text
    basepath,  # type: Text
):
    # type: (...) -> ArtifactURL
    url = ArtifactURL.parse(raw_url)
    if url.is_local_path and not os.path.isabs(url.path):
        abs_path = os.path.normpath(os.path.join(basepath, url.path))
        url = ArtifactURL.from_url_info(url.url_info._replace(path=str(url_quote(abs_path))))
    return url


@attr.s(frozen=True)
class _DirectReference(object):
    project_name = attr.ib()  # type: str
    url = attr.ib()  # type: ArtifactURL
    extras = attr.ib(default=frozenset())  # type: FrozenSet[str]
    marker = attr.ib(default=None)  # type: Optional[Marker]

    @classmethod
    def try_parse(
        cls,
        processed_text,  # type: Text
        basepath,  # type: Text
    ):
        # type: (...) -> Optional[_DirectReference]

        match = re.match(
            r"""
            ^
            (?P<requirement>
                \w+(?:[-_.]+\w+)*
                (?:
                    \s*
                    \[
                        \w+(?:[-_.]+\w+)*
                        (?:
                            \s*
                            ,
                            \s*
                            \w+(?:[-_.]+\w+)*
                        )*
                    ]
                )?
            )
            \s*
            @
            \s*
            (?P<url>\S+)
            (?:
                \s+
                ;
                \s*
                (?P<marker>.+)
            )?
            $
            """,
            processed_text,
            re.VERBOSE,
        )
        if not match:
            return None

        matches = match.groupdict()

        req = Requirement.parse(matches["requirement"])
        marker = None  # type: Optional[Marker]
        raw_marker = matches.get("marker", None)
        if raw_marker:
            marker = Marker(raw_marker)

        raw_url = str(matches["url"])
        url = _parse_url(raw_url, basepath)

        return cls(project_name=req.name, url=url, extras=req.extras, marker=marker)

    @classmethod
    def try_parse_pip_proprietary(
        cls,
        processed_text,  # type: Text
        basepath,  # type: Text
    ):
        # type: (...) -> Optional[_DirectReference]

        url = _parse_url(processed_text, basepath)

        project_names = url.fragment_parameters.get("egg")
        if not project_names:
            return None

        project_name = project_names[-1]
        url = ArtifactURL.from_url_info(
            url.url_info._replace(
                params="",
                # Omit `egg=project_name` since that gets moved to a `project_name @` suffix in
                # `parse_requirement_from_project_name_and_specifier`, but retain all other fragment
                # parameters; notably, subdirectory when present.
                fragment=ArtifactURL.create_fragment(
                    fragment_parameters=parse_qs(url.url_info.fragment), excludes={"egg"}
                ),
            )
        )
        try:
            req = Requirement.parse(project_name)
            return cls(
                project_name=req.name,
                url=url,
                extras=req.extras,
                marker=req.marker,
            )
        except (RequirementParseError, ValueError):
            return cls(project_name=project_name, url=url)


@attr.s(frozen=True)
class _PipRemoteRequirement(object):
    url = attr.ib()  # type: ArtifactURL
    project_name_and_version = attr.ib()  # type: ProjectNameAndVersion
    marker = attr.ib(default=None)  # type: Optional[Marker]

    @classmethod
    def try_parse(cls, processed_text):
        # type: (Text) -> Optional[_PipRemoteRequirement]

        match = re.match(
            r"""
            ^
            (?P<url>\S+)
            (?:
                \s*
                ;
                \s*
                (?P<marker>.+)
            )?
            $
            """,
            processed_text,
            re.VERBOSE,
        )
        if not match:
            return None

        matches = match.groupdict()

        raw_url = str(matches["url"])
        url = ArtifactURL.parse(raw_url)
        if url.is_local_path:
            return None

        marker = None  # type: Optional[Marker]
        raw_marker = matches.get("marker", None)
        if raw_marker:
            marker = Marker(raw_marker)

        try:
            project_name_and_version = ProjectNameAndVersion.from_filename(url.path)
            return cls(url=url, project_name_and_version=project_name_and_version, marker=marker)
        except UnrecognizedDistributionFormat:
            return None


@attr.s(frozen=True)
class _PipLocalRequirement(object):
    url = attr.ib()  # type: ArtifactURL
    path = attr.ib()  # type: str
    extras = attr.ib(default=frozenset())  # type: FrozenSet[str]
    marker = attr.ib(default=None)  # type: Optional[Marker]

    @classmethod
    def try_parse(
        cls,
        processed_text,  # type: Text
        basepath,  # type: Text
    ):
        # type: (...) -> Optional[_PipLocalRequirement]

        url = _parse_url(processed_text, basepath)
        if not url.is_local_path:
            return None

        if processed_text.startswith("file://"):
            scheme_stripped = processed_text[7:]
        elif processed_text.startswith("file:"):
            scheme_stripped = processed_text[5:]
        else:
            scheme_stripped = processed_text
        project_requirement = os.path.basename(scheme_stripped)

        # Requirements strings can optionally include:
        REQUIREMENT_PARTS_START = (
            # + Trailing extras denoted by `[...]`.
            #   See: https://peps.python.org/pep-0508/#extras
            r"\[",
            # + A version specifier denoted by a leading `!=`, `==`, `===`, `>=`, `<=` or `~=`.
            #   See: https://peps.python.org/pep-0508/#grammar
            r"!=><~",
            # + Environment markers denoted by `;...`
            #   See: https://peps.python.org/pep-0508/#environment-markers
            r";",
            # + A trailing whitespace character separating any of the above
            r"\s",
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

        base_name, requirement_parts = match.groups()
        stripped_path = os.path.join(os.path.dirname(scheme_stripped), base_name)
        abs_stripped_path = cast(
            str,
            os.path.normpath(
                os.path.join(basepath, stripped_path)
                if not os.path.isabs(stripped_path)
                else stripped_path
            ),
        )
        if not os.path.exists(abs_stripped_path):
            return None

        # Maybe a local archive or project path.
        requirement_parts = match.group("requirement_parts")
        if not requirement_parts:
            return cls(url=url, path=abs_stripped_path)

        project_requirement = "fake_project{}".format(requirement_parts)
        try:
            req = Requirement.parse(project_requirement)
            return cls(url=url, path=abs_stripped_path, extras=req.extras, marker=req.marker)
        except (RequirementParseError, ValueError):
            return None


def _is_local_project_dir(path):
    # type: (Text) -> bool
    return os.path.isdir(path) and any(
        os.path.isfile(os.path.join(path, p)) for p in ("setup.py", "pyproject.toml")
    )


def _parse_requirement_line(
    line,  # type: LogicalLine
    basepath=None,  # type: Optional[Text]
):
    # type: (...) -> ParsedRequirement

    basepath = basepath or os.getcwd()

    editable, processed_text = _strip_requirement_options(line)

    # Handle PEP-440 direct references (Packaging for Python 2.7 doesn't handle these properly; so
    # we hand roll the parsing of those).
    direct_reference = _DirectReference.try_parse(
        processed_text, basepath=basepath
    ) or _DirectReference.try_parse_pip_proprietary(processed_text, basepath=basepath)
    if direct_reference:
        parsed_scheme = direct_reference.url.scheme
        if "file" == parsed_scheme and _is_local_project_dir(direct_reference.url.path):
            return LocalProjectRequirement(
                line,
                path=direct_reference.url.path,
                extras=direct_reference.extras,
                marker=direct_reference.marker,
                editable=editable,
                project_name=ProjectName(direct_reference.project_name),
            )

        requirement = requirement_from_parts(
            project_name=direct_reference.project_name,
            extras=direct_reference.extras,
            marker=direct_reference.marker,
            editable=editable,
            url=direct_reference.url.raw_url,
        )
        if isinstance(parsed_scheme, VCSScheme):
            parsed_url_info = direct_reference.url.url_info
            url = parsed_url_info._replace(scheme=parsed_scheme.scheme).geturl()
            _, sep, commit = parsed_url_info.path.rpartition("@")
            return VCSRequirement(
                line, parsed_scheme.vcs, url, requirement, commit=commit if sep else None
            )

        return URLRequirement(line, url=direct_reference.url, requirement=requirement)

    # Handle the remaining Pip proprietary formats with no #egg=<project name> fragment.
    pip_remote_requirement = _PipRemoteRequirement.try_parse(processed_text)
    if pip_remote_requirement:
        project_name_and_specifier = _ProjectNameAndSpecifier.from_project_name_and_version(
            pip_remote_requirement.project_name_and_version
        )
        requirement = requirement_from_parts(
            project_name=project_name_and_specifier.project_name,
            specifier=project_name_and_specifier.specifier,
            marker=pip_remote_requirement.marker,
            editable=editable,
            url=pip_remote_requirement.url.raw_url,
        )
        return URLRequirement(line, url=pip_remote_requirement.url, requirement=requirement)

    pip_local_requirement = _PipLocalRequirement.try_parse(processed_text, basepath)
    if pip_local_requirement:
        if _is_local_project_dir(pip_local_requirement.path):
            return LocalProjectRequirement(
                line,
                path=pip_local_requirement.path,
                extras=pip_local_requirement.extras,
                marker=pip_local_requirement.marker,
                editable=editable,
            )
        project_name_and_version = dist_metadata.project_name_and_version(
            pip_local_requirement.path
        )
        if project_name_and_version:
            project_name_and_specifier = _ProjectNameAndSpecifier.from_project_name_and_version(
                project_name_and_version
            )
            requirement = requirement_from_parts(
                project_name=project_name_and_specifier.project_name,
                extras=pip_local_requirement.extras,
                specifier=project_name_and_specifier.specifier,
                marker=pip_local_requirement.marker,
                editable=editable,
            )
            return URLRequirement(line, url=pip_local_requirement.url, requirement=requirement)

    # Handle non-direct-reference PEP-440. See: https://peps.python.org/pep-0440.
    #
    # The `pex.dist_metadata.Requirement.parse` method does all of this for us (via
    # `packaging.requirements.Requirement`) except for the handling of PEP-440 direct url
    # references under older Python versions; which we handled above and won't encounter here.
    try:
        return as_parsed_requirement(Requirement.parse(processed_text), line=line)
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


_REPOS_PARSER = None  # type: Optional[ArgumentParser]


def _parse_repos(line):
    # type: (LogicalLine) -> Iterator[Union[FindLinks, Index]]

    try:
        # The arg-type type ignore is due to Python 2.7 shlex.split not being able to parse unicode
        # strings; but we handle that with a useful error message.
        args = shlex.split(line.processed_text)  # type: ignore[arg-type]
    except UnicodeEncodeError as e:
        raise ParseError(
            line,
            "Options line has unicode characters which are not supported under Python {version}: "
            "{err}".format(version=".".join(map(str, sys.version[:2])), err=e),
        )

    global _REPOS_PARSER
    if _REPOS_PARSER is not None:
        parser = _REPOS_PARSER
    else:
        parser = ArgumentParser()
        # See:
        # + https://pip.pypa.io/en/stable/reference/requirements-file-format/#global-options
        # + https://pip.pypa.io/en/stable/cli/pip_install/#cmdoption-f
        # + https://pip.pypa.io/en/stable/cli/pip_install/#cmdoption-i
        # + https://pip.pypa.io/en/stable/cli/pip_install/#cmdoption-extra-index-url
        parser.add_argument("-f", "--find-links", dest="find_links", action="append", default=[])
        parser.add_argument("-i", "--index-url", dest="index_url")
        parser.add_argument(
            "--extra-index-url", dest="extra_index_urls", action="append", default=[]
        )
        _REPOS_PARSER = parser

    options, _ = parser.parse_known_args(args)

    for find_links in OrderedSet(options.find_links):  # type: OrderedSet[str]
        yield FindLinks(line, location=find_links)

    index_locations = OrderedSet()  # type: OrderedSet[str]
    if options.index_url:
        index_locations.add(options.index_url)
    index_locations.update(options.extra_index_urls)

    for index in index_locations:
        yield Index(line, location=index)


def parse_requirements(
    source,  # type: Source
    fetcher=None,  # type: Optional[URLFetcher]
):
    # type: (...) -> Iterator[Union[ParsedRequirement, Constraint, FindLinks, Index]]

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

            # Skip empty lines and comment lines.
            if not processed_text:
                continue

            if processed_text.startswith("-") and not re.match(
                # N.B.: We deal with editable when parsing requirement lines below.
                r"^(?:-e|--editable)\s.*",
                processed_text,
            ):
                for repo in _parse_repos(logical_line):
                    yield repo
                continue

            # Only requirement lines remain.
            requirement = _parse_requirement_line(
                logical_line, basepath=os.path.dirname(source.origin) if source.is_file else None
            )
            if source.is_constraints:
                if (
                    not isinstance(requirement, (PyPIRequirement, URLRequirement, VCSRequirement))
                    or requirement.requirement.extras
                ):
                    raise ParseError(
                        logical_line,
                        "Constraint files do not support local project requirements and they "
                        "do not support requirements with extras; see:"
                        "https://pip.pypa.io/en/stable/user_guide/#constraints-files. If you are "
                        "using --pip-version vendored or a very old --pip-version, search for 'We "
                        "are also changing our support for Constraints Files' here: "
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
    # type: (...) -> Iterator[Union[ParsedRequirement, Constraint, FindLinks, Index]]
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


def parse_requirement_string(
    requirement,  # type: Text
    basepath=None,  # type: Optional[Text]
):
    # type: (...) -> ParsedRequirement
    return _parse_requirement_line(LogicalLine.from_str(requirement), basepath=basepath)


def parse_requirement_strings(requirements):
    # type: (Iterable[Text]) -> Iterator[ParsedRequirement]
    for requirement in requirements:
        yield parse_requirement_string(requirement)


def as_parsed_requirement(
    requirement,  # type: Requirement
    line=None,  # type: Optional[LogicalLine]
):
    # type: (...) -> ParsedRequirement

    requirement_str = str(requirement)
    logical_line = line or LogicalLine.from_str(requirement_str, source="<parsed requirement>")
    if not requirement.url:
        return PyPIRequirement(line=logical_line, requirement=requirement)

    url = ArtifactURL.parse(requirement.url)
    if isinstance(url.scheme, VCSScheme):
        vcs_scheme = url.scheme
        normalized_url = url.url_info._replace(scheme=vcs_scheme.scheme)
        _, sep, commit = normalized_url.path.rpartition("@")
        return VCSRequirement(
            line=logical_line,
            vcs=vcs_scheme.vcs,
            url=normalized_url.geturl(),
            requirement=requirement,
            commit=commit,
        )

    if url.is_local_path and os.path.isdir(url.path):
        return LocalProjectRequirement(
            line=logical_line,
            path=url.path,
            extras=tuple(requirement.extras),
            marker=requirement.marker,
            editable=requirement.editable,
            project_name=requirement.project_name,
        )

    return URLRequirement(line=logical_line, url=url, requirement=requirement)
