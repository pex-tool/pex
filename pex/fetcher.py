# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import contextlib
import os
import socket
import sys
import threading
import time
from contextlib import closing, contextmanager

from pex.auth import PasswordDatabase, PasswordEntry
from pex.compatibility import (
    PY2,
    AbstractHTTPHandler,
    FileHandler,
    HTTPBasicAuthHandler,
    HTTPConnection,
    HTTPDigestAuthHandler,
    HTTPError,
    HTTPPasswordMgrWithDefaultRealm,
    HTTPResponse,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
    in_main_thread,
    urlparse,
)
from pex.exceptions import production_assert
from pex.network_configuration import NetworkConfiguration
from pex.typing import TYPE_CHECKING, cast
from pex.version import __version__

if TYPE_CHECKING:
    from ssl import SSLContext
    from typing import Any, BinaryIO, Dict, Iterable, Iterator, Mapping, Optional, Text

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

        # These shenanigans deserve some explanation, since, in OpenSSL 3.0 anyhow, it is perfectly
        # fine to create an SSL Context (`SSL_CTX_new`) in any thread:
        #
        # It turns out that, in typical use, the CPython ssl module hides OpenSSL configuration
        # issues through no real fault of its own. This is due to the fact that an import of the
        # `ssl` module, which generally happens in the main thread, triggers, through instantiation
        # of the `ssl.Purpose` enum type [^1] a call to OpenSSL's `OBJ_obj2nid` [^2][^3] which
        # loads OpenSSL config but throws away the return value; thus hiding errors in config. Since
        # the OpenSSL config scheme is to load it at most once per thread, this means subsequent
        # OpenSSL call paths in the same thread that imported `ssl` (like the one generated via
        # `ssl.create_default_context`) that _do_ check the return value of config loading [^4][^5],
        # will not have to load config (since it's been done once already in the thread) and thus
        # will not get the chance to check the config load function return value and will thus not
        # error. This default behavior is almost certainly bad, since it allows invalid OpenSSL
        # configs to go partially read at best. That said, this is the default Python
        # single-threaded behavior and, right or wrong, we preserve that here by forcing our SSL
        # initialization to happen in the main thread, keeping any OpenSSL misconfiguration silently
        # ignored.
        #
        # The only solace here is that the use cases where OpenSSL config can be bad on a machine
        # and the machine still function are narrow. The case we know of, that triggered creation of
        # this machinery, involves the combination of a modern PBS Python [^6] (which has a vanilla
        # OpenSSL statically linked into the Python binary) running on a RedHat OS that expresses
        # custom RedHat configuration keys [^7] in its OpenSSL config. These custom keys are only
        # supported by RedHat patches to OpenSSL and cause vanilla versions of OpenSSL to error when
        # loading config due to unknown configuration options.
        #
        # [^1]: https://github.com/python/cpython/blob/5a173efa693a053bf4a059c82c1c06c82a9fa8fb/Lib/ssl.py#L394-L419
        # [^2]: https://github.com/python/cpython/blob/5a173efa693a053bf4a059c82c1c06c82a9fa8fb/Modules/_ssl.c#L5534-L5552
        # [^3]: https://github.com/openssl/openssl/blob/c3cc0f1386b0544383a61244a4beeb762b67498f/crypto/objects/obj_dat.c#L326-L340
        # [^4]: https://github.com/openssl/openssl/blob/c3cc0f1386b0544383a61244a4beeb762b67498f/ssl/ssl_lib.c#L3194-L3212
        # [^5]: https://github.com/openssl/openssl/blob/c3cc0f1386b0544383a61244a4beeb762b67498f/ssl/ssl_init.c#L86-L116
        # [^6]: https://github.com/astral-sh/python-build-standalone/releases/tag/20240107
        # [^7]: https://gitlab.com/redhat-crypto/fedora-crypto-policies/-/merge_requests/110/diffs#269a48e71ac25ad1d07ff00db2390834c8ba7596_11_16
        production_assert(
            in_main_thread(),
            "An SSLContext must be initialized from the main thread. An attempt was made to "
            "initialize an SSLContext for {cert_config} from thread {thread}.",
            cert_config=self,
            thread=threading.current_thread(),
        )
        with guard_stdout():
            # We import ssl lazily as an affordance to PEXes that use gevent SSL monkeypatching,
            # which requires (and checks) that the `ssl` module is not imported priory to the
            # `from gevent import monkey; monkey.patch_all()` call.
            #
            # See: https://github.com/pex-tool/pex/issues/2415
            import ssl

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
            UnixHTTPHandler(),
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
