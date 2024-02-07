# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import contextlib
import os
import ssl
import sys
import threading
import time
from contextlib import closing, contextmanager
from ssl import SSLContext

from pex import asserts
from pex.auth import PasswordDatabase, PasswordEntry
from pex.compatibility import (
    FileHandler,
    HTTPBasicAuthHandler,
    HTTPDigestAuthHandler,
    HTTPError,
    HTTPPasswordMgrWithDefaultRealm,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
    in_main_thread,
)
from pex.network_configuration import NetworkConfiguration
from pex.typing import TYPE_CHECKING, cast
from pex.version import __version__

if TYPE_CHECKING:
    from typing import BinaryIO, Dict, Iterable, Iterator, Mapping, Optional, Text

    import attr  # vendor:skip
else:
    BinaryIO = None
    from pex.third_party import attr


@contextmanager
def guard_stdout():
    # type: () -> Iterator[None]
    # Under PyPy 3.9 and 3.10, `ssl.create_default_context` causes spurious informational text about
    # SSL certs to be emitted to stdout; so we squelch this.
    if hasattr(sys, "pypy_version_info") and sys.version_info[:2] >= (3, 9):
        with open(os.devnull, "w") as fp:
            # The `contextlib.redirect_stdout` function is available for Python 3.4+.
            with contextlib.redirect_stdout(fp):  # type: ignore[attr-defined]
                yield
    else:
        yield


@attr.s(frozen=True)
class _CertConfig(object):
    @classmethod
    def create(cls, network_configuration=None):
        # type: (Optional[NetworkConfiguration]) -> _CertConfig
        if network_configuration is None:
            return cls()
        return cls(cert=network_configuration.cert, client_cert=network_configuration.client_cert)

    cert = attr.ib(default=None)  # type: Optional[str]
    client_cert = attr.ib(default=None)  # type: Optional[str]

    def create_ssl_context(self):
        # type: () -> SSLContext
        asserts.production_assert(
            in_main_thread(),
            msg=(
                "An SSLContext must be initialized from the main thread. An attempt was made to "
                "initialize an SSLContext for {cert_config} from thread {thread}.".format(
                    cert_config=self, thread=threading.current_thread()
                )
            ),
        )
        with guard_stdout():
            ssl_context = ssl.create_default_context(cafile=self.cert)
            if self.client_cert:
                ssl_context.load_cert_chain(self.client_cert)
            return ssl_context


_SSL_CONTEXTS = {}  # type: Dict[_CertConfig, SSLContext]


def get_ssl_context(network_configuration=None):
    # type: (Optional[NetworkConfiguration]) -> SSLContext
    cert_config = _CertConfig.create(network_configuration=network_configuration)
    ssl_context = _SSL_CONTEXTS.get(cert_config)
    if not ssl_context:
        ssl_context = cert_config.create_ssl_context()
        _SSL_CONTEXTS[cert_config] = ssl_context
    return ssl_context


def initialize_ssl_context(network_configuration=None):
    # type: (Optional[NetworkConfiguration]) -> None
    get_ssl_context(network_configuration=network_configuration)


# N.B.: We eagerly initialize an SSLContext for the default case of no CA cert and no client cert.
# When a custom CA cert or client cert or both are configured, that code will need to call
# initialize_ssl_context on its own.
initialize_ssl_context()


class URLFetcher(object):
    USER_AGENT = "pex/{version}".format(version=__version__)

    def __init__(
        self,
        network_configuration=None,  # type: Optional[NetworkConfiguration]
        handle_file_urls=False,  # type: bool
        password_entries=(),  # type: Iterable[PasswordEntry]
        netrc_file="~/.netrc",  # type: Optional[str]
    ):
        # type: (...) -> None
        network_configuration = network_configuration or NetworkConfiguration()

        self._timeout = network_configuration.timeout
        self._max_retries = network_configuration.retries

        proxies = None  # type: Optional[Dict[str, str]]
        if network_configuration.proxy:
            proxies = {protocol: network_configuration.proxy for protocol in ("http", "https")}

        handlers = [
            ProxyHandler(proxies),
            HTTPSHandler(context=get_ssl_context(network_configuration=network_configuration)),
        ]
        if handle_file_urls:
            handlers.append(FileHandler())

        self._password_database = PasswordDatabase.from_netrc(netrc_file=netrc_file).append(
            password_entries
        )
        self._handlers = tuple(handlers)

    @contextmanager
    def get_body_stream(
        self,
        url,  # type: Text
        extra_headers=None,  # type: Optional[Mapping[str, str]]
    ):
        # type: (...) -> Iterator[BinaryIO]

        handlers = list(self._handlers)
        if self._password_database.entries:
            password_manager = HTTPPasswordMgrWithDefaultRealm()
            for password_entry in self._password_database.entries:
                # N.B.: The password manager adds a second entry implicitly if the URI we hand it
                # does not include port information (80 for http URIs and 443 for https URIs).
                password_manager.add_password(
                    realm=None,
                    uri=password_entry.uri_or_default(url),
                    user=password_entry.username,
                    passwd=password_entry.password,
                )
            handlers.extend(
                (HTTPBasicAuthHandler(password_manager), HTTPDigestAuthHandler(password_manager))
            )

        retries = 0
        retry_delay_secs = 0.1
        last_error = None  # type: Optional[Exception]
        while retries <= self._max_retries:
            if retries > 0:
                time.sleep(retry_delay_secs)
                retry_delay_secs *= 2

            opener = build_opener(*handlers)
            headers = dict(extra_headers) if extra_headers else {}
            headers["User-Agent"] = self.USER_AGENT
            request = Request(
                # N.B.: MyPy incorrectly thinks url must be a str in Python 2 where a unicode url
                # actually works fine.
                url,  # type: ignore[arg-type]
                headers=headers,
            )
            # The fp is typed as Optional[...] for Python 2 only in the typeshed. A `None`
            # can only be returned if a faulty custom handler is installed and we only
            # install stdlib handlers.
            fp = cast(BinaryIO, opener.open(request, timeout=self._timeout))
            try:
                with closing(fp) as body_stream:
                    yield body_stream
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

    @contextmanager
    def get_body_iter(self, url):
        # type: (Text) -> Iterator[Iterator[Text]]
        with self.get_body_stream(url) as body_stream:
            yield (line.decode("utf-8") for line in body_stream.readlines())
