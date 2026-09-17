# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import socket
import time
from contextlib import closing, contextmanager

from pex.auth import PasswordDatabase, PasswordEntry
from pex.compatibility import PY2, PY3, HTTPError, urlparse
from pex.fetcher.ssl import get_ssl_context
from pex.network_configuration import NetworkConfiguration
from pex.typing import TYPE_CHECKING, cast
from pex.version import __version__

if PY3:
    from http.client import HTTPConnection, HTTPResponse
    from urllib.request import (
        AbstractHTTPHandler,
        FileHandler,
        HTTPBasicAuthHandler,
        HTTPDigestAuthHandler,
        HTTPPasswordMgrWithDefaultRealm,
        HTTPSHandler,
        ProxyHandler,
        Request,
        build_opener,
    )
else:
    from httplib import HTTPConnection, HTTPResponse
    from urllib2 import (
        AbstractHTTPHandler,
        FileHandler,
        HTTPBasicAuthHandler,
        HTTPDigestAuthHandler,
        HTTPPasswordMgrWithDefaultRealm,
        HTTPSHandler,
        ProxyHandler,
        Request,
        build_opener,
    )

if TYPE_CHECKING:
    from typing import Any, BinaryIO, Dict, Iterable, Iterator, Mapping, Optional, Text


class UnixHTTPConnection(HTTPConnection):
    def __init__(
        self,
        *args,  # type: Any
        **kwargs  # type: Any
    ):
        # type: (...) -> None
        path = kwargs.pop("path")
        super(UnixHTTPConnection, self).__init__(*args, **kwargs)
        self.path = path

    def connect(self):
        # type: () -> None
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.path)
        self.sock = sock


class UnixHTTPHandler(AbstractHTTPHandler):
    # N.B.: The naming scheme here is <protocol>_<action>; thus `unix` captures unix:// URLs and
    # `open` captures the open event for unix:// URLs.
    def unix_open(self, req):
        # type: (Request) -> HTTPResponse
        url_info = urlparse.urlparse(req.get_full_url())

        path = ""
        unix_socket_path = url_info.path
        while not os.path.basename(unix_socket_path).endswith(".sock"):
            path = os.path.join(path, os.path.basename(unix_socket_path))
            new_unix_socket_path = os.path.dirname(unix_socket_path)
            if new_unix_socket_path == unix_socket_path:
                # There was no *.sock component, so just use the full path.
                path = ""
                unix_socket_path = url_info.path
                break
            unix_socket_path = new_unix_socket_path

        # <scheme>://<netloc>/<path>;<params>?<query>#<fragment>
        url = urlparse.urlunparse(
            ("unix", "localhost", path, url_info.params, url_info.query, url_info.fragment)
        )
        kwargs = {} if PY2 else {"method": req.get_method()}
        modified_req = Request(
            url,
            data=req.data,
            headers=req.headers,
            # N.B.: MyPy for Python 2.7 needs the cast.
            origin_req_host=cast(str, req.origin_req_host),
            unverifiable=req.unverifiable,
            **kwargs
        )

        # The stdlib actually sets timeout this way - it is not a constructor argument in any
        # Python version.
        modified_req.timeout = req.timeout

        # N.B.: MyPy for Python 2.7 needs the cast.
        return cast(
            HTTPResponse, self.do_open(UnixHTTPConnection, modified_req, path=unix_socket_path)
        )


def scheme_guard(auth_handler):
    # type: (Any) -> Any
    http_error_401 = getattr(auth_handler, "http_error_401", None)
    if not http_error_401:
        return auth_handler

    def guard(*args, **kwargs):
        try:
            return http_error_401(*args, **kwargs)
        except ValueError:
            return None

    setattr(auth_handler, "http_error_401", guard)
    return auth_handler


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
        self._proxy = network_configuration.proxy  # type: Optional[str]
        self._cert = network_configuration.cert  # type: Optional[str]

        proxies = None  # type: Optional[Dict[str, str]]
        if network_configuration.proxy:
            proxies = {protocol: network_configuration.proxy for protocol in ("http", "https")}

        handlers = [
            ProxyHandler(proxies),
            HTTPSHandler(context=get_ssl_context(network_configuration=network_configuration)),
            UnixHTTPHandler(),
        ]
        if handle_file_urls:
            handlers.append(FileHandler())

        self._password_database = PasswordDatabase.from_netrc(netrc_file=netrc_file).append(
            password_entries
        )
        self._handlers = tuple(handlers)

    def network_env(self):
        # type: () -> Dict[str, str]
        env = {}  # type: Dict[str, str]
        if self._proxy:
            env.update(
                ("{protocol}_proxy".format(protocol=protocol), self._proxy)
                for protocol in ("http", "https")
            )
        if self._cert:
            env["SSL_CERT_DIR" if os.path.isdir(self._cert) else "SSL_CERT_FILE"] = self._cert
        return env

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
                (
                    HTTPBasicAuthHandler(password_manager),
                    # N.B.: Python stdlib HTTPDigestAuthHandler docs note:
                    # > Changed in version 3.3: Raise ValueError on unsupported Authentication
                    # > Scheme.
                    # We saw this in the wild in https://github.com/pex-tool/pex/issues/3224; so we
                    # hack around this by guarding against the ValueError raise here.
                    #
                    # Likely, it would be better to just remove this auth handler altogether -
                    # Digest auth would seem to be rarely used in the contexts Pex runs in. That
                    # said, this would be a backward compatibility break for anyone that happened to
                    # rely on it.
                    scheme_guard(HTTPDigestAuthHandler(password_manager)),
                )
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
            fp = cast("BinaryIO", opener.open(request, timeout=self._timeout))
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
