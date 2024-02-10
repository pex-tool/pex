# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import re
from netrc import NetrcParseError, netrc

from pex import pex_warnings
from pex.compatibility import urlparse
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Iterator, Optional, Text, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Machine(object):
    @classmethod
    def from_url_info(cls, url_info):
        # type: (urlparse.ParseResult) -> Machine

        if not url_info.scheme:
            raise ValueError(
                "Expected a scheme for the BaseURL. Given: {url_info}".format(url_info=url_info)
            )

        if "file" == url_info.scheme:
            return cls(reduced_url="file://{path}".format(path=url_info.path))

        if not url_info.hostname:
            raise ValueError(
                "Expected a hostname for a BaseURL with {scheme} scheme. Given: {url_info}".format(
                    scheme=url_info.scheme, url_info=url_info
                )
            )

        return cls(
            reduced_url="{scheme}://{host}{port}".format(
                scheme=url_info.scheme,
                host=url_info.hostname,
                port=":{port}".format(port=url_info.port) if url_info.port is not None else "",
            ),
            host=url_info.hostname,
            port=url_info.port,
        )

    @classmethod
    def from_url(cls, url):
        # type: (Text) -> Machine
        return cls.from_url_info(urlparse.urlparse(url))

    reduced_url = attr.ib()  # type: str
    host = attr.ib(default=None)  # type: Optional[str]
    port = attr.ib(default=None)  # type: Optional[int]


@attr.s(frozen=True)
class PasswordEntry(object):
    @classmethod
    def maybe_extract_from_url(cls, url):
        # type: (str) -> Optional[PasswordEntry]
        url_info = urlparse.urlparse(url)
        if not url_info.username or not url_info.password:
            return None

        return cls(
            machine=Machine.from_url_info(url_info),
            username=url_info.username,
            password=url_info.password,
        )

    username = attr.ib()  # type: str
    password = attr.ib()  # type: str
    machine = attr.ib(default=None)  # type: Optional[Machine]

    def uri_or_default(self, url):
        # type: (Text) -> str
        return (self.machine or Machine.from_url(url)).reduced_url

    def maybe_inject_in_url(self, url):
        # type: (str) -> Optional[str]
        url_info = urlparse.urlparse(url)

        if url_info.username or url_info.password:
            # Don't stomp credentials already embedded in an URL.
            return None

        if self.machine:
            if Machine.from_url_info(url_info) != self.machine:
                return None

        scheme, netloc, path, params, query, fragment = url_info
        netloc = "{username}:{password}@{netloc}".format(
            username=self.username, password=self.password, netloc=netloc
        )
        return urlparse.urlunparse((scheme, netloc, path, params, query, fragment))


@attr.s(frozen=True)
class PasswordDatabase(object):
    @classmethod
    def from_netrc(cls, netrc_file="~/.netrc"):
        # type: (Optional[str]) -> PasswordDatabase
        if not netrc_file:
            return cls()

        netrc_path = os.path.expanduser(netrc_file)
        if not os.path.isfile(netrc_path):
            return cls()

        try:
            netrc_database = netrc(netrc_path)
        except NetrcParseError as e:
            pex_warnings.warn(
                "Failed to load netrc credentials: {err}\n"
                "Continuing without netrc credentials.".format(err=e)
            )
            return cls()

        def iter_entries():
            # type: () -> Iterator[PasswordEntry]
            for machine, (login, _, password) in netrc_database.hosts.items():
                if password is None:
                    continue

                if machine == "default":
                    # The `default` entry is special and means just that; so we omit any qualifying
                    # machine.
                    yield PasswordEntry(username=login, password=password)

                # Traditionally, ~/.netrc machine entries just contain a bare hostname but we allow
                # for them containing a scheme since the format is so poorly documented and really
                # used as the beholder sees fit (it's a shared ~community format at this point and
                # used differently by a wide range of tools; I think FTP originally - thus it has
                # `macros` entries which ~no-one knows about / uses).
                #
                # For scheme syntax, see: https://datatracker.ietf.org/doc/html/rfc3986#section-3.1
                if re.search(r"^(?P<scheme>[a-zA-Z][a-zA-Z\d+.-]*)://", machine):
                    yield PasswordEntry(
                        machine=Machine.from_url(machine),
                        username=login,
                        password=password,
                    )
                    continue

                for scheme in "http", "https":
                    yield PasswordEntry(
                        machine=Machine.from_url(
                            "{scheme}://{machine}".format(scheme=scheme, machine=machine)
                        ),
                        username=login,
                        password=password,
                    )

        return cls(entries=tuple(iter_entries()))

    entries = attr.ib(default=())  # type: Tuple[PasswordEntry, ...]

    def append(self, entries):
        # type: (Iterable[PasswordEntry]) -> PasswordDatabase
        return PasswordDatabase(entries=self.entries + tuple(entries))
