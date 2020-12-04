# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import re
import ssl
import time
from collections import namedtuple
from contextlib import closing, contextmanager

from pex.compatibility import (
    HTTPError,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
    to_unicode,
    urlparse,
)
from pex.network_configuration import NetworkConfiguration
from pex.third_party.packaging.markers import Marker
from pex.third_party.pkg_resources import Requirement, RequirementParseError
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import BinaryIO, Dict, Iterator, Match, Optional, Text, Tuple, Union, Iterable


class LogicalLine(
    namedtuple("LogicalLine", ["raw_text", "processed_text", "source", "start_line", "end_line"])
):
    @property
    def raw_text(self):
        # type: () -> str
        return cast(str, super(LogicalLine, self).raw_text)

    @property
    def processed_text(self):
        # type: () -> str
        return cast(str, super(LogicalLine, self).processed_text)

    @property
    def source(self):
        # type: () -> str
        return cast(str, super(LogicalLine, self).source)

    @property
    def start_line(self):
        # type: () -> int
        return cast(int, super(LogicalLine, self).start_line)

    @property
    def end_line(self):
        # type: () -> int
        return cast(int, super(LogicalLine, self).end_line)

    def render_location(self):
        # type: () -> str
        if self.start_line == self.end_line:
            return "{} line {}".format(self.source, self.start_line)
        return "{} lines {}-{}".format(self.source, self.start_line, self.end_line)


class URLFetcher(object):
    def __init__(self, network_configuration=None):
        # type: (Optional[NetworkConfiguration]) -> None
        network_configuration = network_configuration or NetworkConfiguration.create()

        self._timeout = network_configuration.timeout
        self._max_retries = network_configuration.retries
        self._headers = network_configuration.headers_as_dict()

        ssl_context = ssl.create_default_context(cafile=network_configuration.cert)
        if network_configuration.client_cert:
            ssl_context.load_cert_chain(network_configuration.client_cert)

        proxies = None  # type: Optional[Dict[str, str]]
        if network_configuration.proxy:
            proxies = {
                protocol: network_configuration.proxy for protocol in ("ftp", "http", "https")
            }

        self._handlers = (ProxyHandler(proxies), HTTPSHandler(context=ssl_context))

    @contextmanager
    def get_body_iter(self, url):
        # type: (str) -> Iterator[Iterator[Text]]
        retries = 0
        retry_delay_secs = 0.1
        last_error = None  # type: Optional[Exception]
        while retries <= self._max_retries:
            if retries > 0:
                time.sleep(retry_delay_secs)
                retry_delay_secs *= 2

            opener = build_opener(*self._handlers)
            request = Request(url, headers=self._headers)
            try:
                with closing(opener.open(request, timeout=self._timeout)) as fp:
                    # The fp is typed as Optional[...] for Python 2 only in the typeshed. A `None`
                    # can only be returned if a faulty custom handler is installed and we only
                    # install stdlib handlers.
                    body_stream = cast("BinaryIO", fp)
                    yield (to_unicode(line) for line in body_stream.readlines())
                    return
            except HTTPError as e:
                # See: https://tools.ietf.org/html/rfc2616#page-39
                if e.code not in (
                    408,  # Request Time-out
                    500,  # Internal Server Error
                    503,  # Service Unavailable
                    504,  # Gateway Time-out
                ):
                    raise e
                last_error = e
            except (IOError, OSError) as e:
                # Unfortunately errors are overly broad at this point. We can get either OSError or
                # URLError (a subclass of OSError) which at times indicates retryable socket level
                # errors. Since retrying a non-retryable socket level error just wastes local
                # machine resources we err towards always retrying.
                last_error = e
            finally:
                retries += 1

        raise cast(Exception, last_error)


class Source(namedtuple("Source", ["origin", "is_file", "is_constraints", "lines"])):
    @classmethod
    @contextmanager
    def from_url(
        cls,
        fetcher,  # type: URLFetcher
        url,  # type: str
        is_constraints=False,  # type: bool
    ):
        # type: (...) -> Iterator[Source]
        with fetcher.get_body_iter(url) as lines:
            yield cls(origin=url, is_file=False, is_constraints=is_constraints, lines=lines)

    @classmethod
    @contextmanager
    def from_file(
        cls,
        path,  # type: str
        is_constraints=False,  # type: bool
    ):
        # type: (...) -> Iterator[Source]
        realpath = os.path.realpath(path)
        with open(realpath) as fp:
            yield cls(origin=realpath, is_file=True, is_constraints=is_constraints, lines=fp)

    @classmethod
    def from_text(
        cls,
        contents,  # type: str
        origin="<string>",  # type: str
        is_constraints=False,  # type: bool
    ):
        # type: (...) -> Source
        return cls(
            origin=origin,
            is_file=False,
            is_constraints=is_constraints,
            lines=contents.splitlines(True),  # This is keepends=True.
        )

    @property
    def origin(self):
        # type: () -> str
        return cast(str, super(Source, self).origin)

    @property
    def is_file(self):
        return cast(bool, super(Source, self).is_file)

    @property
    def is_constraints(self):
        return cast(bool, super(Source, self).is_constraints)

    @property
    def lines(self):
        # type: () -> Iterator[str]
        return cast("Iterator[str]", super(Source, self).lines)

    @contextmanager
    def resolve(
        self,
        line,  # type: LogicalLine
        origin,  # type: str
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
                with self.from_url(fetcher, origin) as source:
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


class ReqInfo(
    namedtuple("ReqInfo", ["line", "project_name", "url", "marker", "editable", "is_local_project"])
):
    @classmethod
    def create(
        cls,
        line,  # type: LogicalLine
        project_name=None,  # type: Optional[str]
        url=None,  # type: Optional[str]
        marker=None,  # type: Optional[Marker]
        editable=False,  # type: bool
        is_local_project=False,  # type: bool
    ):
        # type: (...) -> ReqInfo
        return cls(
            line=line,
            project_name=project_name,
            url=url,
            marker=marker,
            editable=editable,
            is_local_project=is_local_project,
        )

    @property
    def line(self):
        # type: () -> LogicalLine
        return cast(LogicalLine, super(ReqInfo, self).line)

    @property
    def project_name(self):
        # type: () -> Optional[str]
        return cast("Optional[str]", super(ReqInfo, self).project_name)

    @property
    def url(self):
        # type: () -> Optional[str]
        return cast("Optional[str]", super(ReqInfo, self).url)

    @property
    def marker(self):
        # type: () -> Optional[Marker]
        return cast("Optional[Marker]", super(ReqInfo, self).marker)

    @property
    def editable(self):
        # type: () -> bool
        return cast(bool, super(ReqInfo, self).editable)

    @property
    def is_local_project(self):
        # type: () -> bool
        return cast(bool, super(ReqInfo, self).is_local_project)


class Constraint(namedtuple("Constraint", ["req_info"])):
    @property
    def req_info(self):
        # type: () -> ReqInfo
        return cast(ReqInfo, super(Constraint, self).req_info)


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
    # type: (LogicalLine) -> Tuple[bool, str]

    processed_text = re.sub(r"^\s*(-e|--editable)\s+", "", line.processed_text)
    editable = processed_text != line.processed_text
    return editable, re.sub(r"\s--(global-option|install-option|hash).*$", "", processed_text)


def _is_recognized_pip_url_scheme(scheme):
    # type: (str) -> bool
    return bool(
        re.match(
            r"""
            (
                # Archives
                  file
                | ftp
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


def _try_parse_fragment_project_name_and_marker(fragment):
    # type: (str) -> Tuple[Optional[str], Optional[Marker]]
    project_requirement = None
    for part in fragment.split("&"):
        if part.startswith("egg="):
            _, project_requirement = part.split("=", 1)
            break
    if project_requirement is None:
        return None, None
    try:
        req = Requirement.parse(project_requirement)
        return req.name, req.marker
    except (RequirementParseError, ValueError):
        return project_requirement, None


def _try_parse_project_name_from_path(path):
    # type: (str) -> Optional[str]
    fname = os.path.basename(path).strip()

    # Handle wheels:
    #
    # The wheel filename convention is specified here:
    #   https://www.python.org/dev/peps/pep-0427/#file-name-convention.
    if fname.endswith(".whl"):
        project_name, _ = fname.split("-", 1)
        return project_name

    # Handle sdists:
    #
    # The sdist name format is specified here:
    #   https://www.python.org/dev/peps/pep-0625/#specification.
    # We allow a few more legacy extensions.
    if fname.endswith((".tar.gz", ".zip")):
        project_name, _ = fname.rsplit("-", 1)
        return project_name

    return None


def _try_parse_pip_local_formats(
    path,  # type: str
    basepath=None,  # type: Optional[str]
):
    # type: (...) -> Tuple[Optional[str], Optional[Marker]]
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
        return None, None

    directory_name, requirement_parts = match.groups()
    stripped_path = os.path.join(os.path.dirname(path), directory_name)
    abs_stripped_path = (
        os.path.join(basepath, stripped_path) if basepath else os.path.abspath(stripped_path)
    )
    if not os.path.exists(abs_stripped_path):
        return None, None

    if not os.path.isdir(abs_stripped_path):
        # Maybe a local archive path.
        return abs_stripped_path, None

    # Maybe a local project path.
    requirement_parts = match.group("requirement_parts")
    if not requirement_parts:
        return abs_stripped_path, None

    project_requirement = "fake_project{}".format(requirement_parts)
    try:
        req = Requirement.parse(project_requirement)
        return abs_stripped_path, req.marker
    except (RequirementParseError, ValueError):
        return None, None


def _split_direct_references(processed_text):
    # type: (str) -> Tuple[str, Optional[str]]
    parts = processed_text.split("@", 1)
    if len(parts) == 1:
        return processed_text, None
    return parts[0].strip(), parts[1].strip()


def _parse_requirement_line(
    line,  # type: LogicalLine
    basepath=None,  # type: Optional[str]
):
    # type: (...) -> ReqInfo

    basepath = basepath or os.getcwd()

    editable, processed_text = _strip_requirement_options(line)

    # Handle urls (Pip proprietary).
    parsed_url = urlparse.urlparse(processed_text)
    if _is_recognized_pip_url_scheme(parsed_url.scheme):
        project_name, marker = _try_parse_fragment_project_name_and_marker(parsed_url.fragment)
        if not project_name:
            project_name = _try_parse_project_name_from_path(parsed_url.path)
        url = parsed_url._replace(fragment="").geturl()
        return ReqInfo.create(
            line, project_name=project_name, url=url, marker=marker, editable=editable
        )

    # Handle local archives and project directories (Pip proprietary).
    maybe_abs_path, marker = _try_parse_pip_local_formats(processed_text, basepath=basepath)
    if maybe_abs_path is not None and any(
        os.path.isfile(os.path.join(maybe_abs_path, *p))
        for p in ((), ("setup.py",), ("pyproject.toml",))
    ):
        archive_or_project_path = os.path.realpath(maybe_abs_path)
        is_local_project = os.path.isdir(archive_or_project_path)
        project_name = (
            None if is_local_project else _try_parse_project_name_from_path(archive_or_project_path)
        )
        return ReqInfo.create(
            line,
            project_name=project_name,
            url=archive_or_project_path,
            marker=marker,
            editable=editable,
            is_local_project=is_local_project,
        )

    # Handle PEP-440. See: https://www.python.org/dev/peps/pep-0440.
    #
    # The `pkg_resources.Requirement.parse` method does all of this for us (via
    # `packaging.requirements.Requirement`) except for the handling of PEP-440 direct url
    # references; so we strip those urls out first.
    requirement, direct_reference_url = _split_direct_references(processed_text)
    try:
        req = Requirement.parse(requirement)
        return ReqInfo.create(
            line,
            project_name=req.name,
            url=direct_reference_url or req.url,
            marker=req.marker,
            editable=editable,
        )
    except RequirementParseError as e:
        raise ParseError(
            line, "Problem parsing {!r} as a requirement: {}".format(processed_text, e)
        )


def _expand_env_var(line, match):
    # type: (LogicalLine, Match) -> str
    env_var_name = match.group(1)
    value = os.environ.get(env_var_name)
    if value is None:
        raise ParseError(line, "No value for environment variable ${} is set.".format(env_var_name))
    return value


def _expand_env_vars(line):
    # type: (LogicalLine) -> str
    # We afford for lowercase letters here over and above the spec.
    # See: https://pubs.opengroup.org/onlinepubs/007908799/xbd/envvar.html

    def expand_env_var(match):
        # type: (Match) -> str
        return _expand_env_var(line, match)

    return re.sub(r"\${([A-Za-z0-9_]+)}", expand_env_var, line.processed_text)


def _get_parameter(line):
    # type: (LogicalLine) -> str
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
    # type: (...) -> Iterator[Union[ReqInfo, Constraint]]

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
        logical_line = logical_line._replace(processed_text=_expand_env_vars(logical_line))
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
                    for req_info in parse_requirements(other_source, fetcher=fetcher):
                        yield req_info
                continue

            # Skip empty lines, comment lines and all other Pip options.
            if not processed_text or processed_text.startswith("-"):
                continue

            # Only requirement lines remain.
            req_info = _parse_requirement_line(
                logical_line, basepath=os.path.dirname(source.origin) if source.is_file else None
            )
            yield Constraint(req_info) if source.is_constraints else req_info
        finally:
            start_line = 0
            del line_buffer[:]
            del logical_line_buffer[:]


def parse_requirement_file(
    path,  # type: str
    is_constraints=False,  # type: bool
    fetcher=None,  # type: Optional[URLFetcher]
):
    # type: (...) -> Iterator[Union[ReqInfo, Constraint]]
    with Source.from_file(path, is_constraints=is_constraints) as source:
        for req_info in parse_requirements(source, fetcher=fetcher):
            yield req_info


def parse_requirement_strings(requirements):
    # type: (Iterable[str]) -> Iterator[ReqInfo]
    for requirement in requirements:
        yield _parse_requirement_line(
            LogicalLine(
                raw_text=requirement,
                processed_text=requirement,
                source="<string>",
                start_line=1,
                end_line=1,
            )
        )
