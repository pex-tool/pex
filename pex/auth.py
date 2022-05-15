# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
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
class PasswordEntry(object):
    @staticmethod
    def _reduced_url(url_info):
        # type: (urlparse.ParseResult) -> str
        return "{scheme}://{host}{port}".format(
            scheme=url_info.scheme,
            host=url_info.hostname,
            port=":{port}".format(port=url_info.port) if url_info.port is not None else "",
        )

    @classmethod
    def maybe_extract_from_url(cls, url):
        # type: (str) -> Optional[PasswordEntry]
        url_info = urlparse.urlparse(url)
        if not url_info.username or not url_info.password:
            return None

        return cls(
            uri=cls._reduced_url(url_info),
            username=url_info.username,
            password=url_info.password,
        )

    username = attr.ib()  # type: str
    password = attr.ib()  # type: str
    uri = attr.ib(default=None)  # type: Optional[str]

    def uri_or_default(self, url):
        # type: (Text) -> str
        return self.uri or self._reduced_url(urlparse.urlparse(url))


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
                    # URI.
                    yield PasswordEntry(username=login, password=password)

                # Traditionally, ~/.netrc machine entries just contain a bare hostname but we allow
                # for them containing a scheme since the format is so poorly documented and really
                # used as the beholder sees fit (it's a shared ~community format at this point and
                # used differently by a wide range of tools; I think FTP originally - thus it has
                # `macros` entries which ~no-one knows about / uses).
                if urlparse.urlparse(machine).scheme:
                    yield PasswordEntry(uri=machine, username=login, password=password)
                    continue

                for scheme in "http", "https":
                    yield PasswordEntry(
                        uri="{scheme}://{machine}".format(scheme=scheme, machine=machine),
                        username=login,
                        password=password,
                    )

        return cls(entries=tuple(iter_entries()))

    entries = attr.ib(default=())  # type: Tuple[PasswordEntry, ...]

    def append(self, entries):
        # type: (Iterable[PasswordEntry]) -> PasswordDatabase
        return PasswordDatabase(entries=self.entries + tuple(entries))
