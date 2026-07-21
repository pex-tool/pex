# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import base64
from threading import Thread

import pytest

from pex.auth import Machine, PasswordEntry
from pex.compatibility import PY2, HTTPError
from pex.fetcher import URLFetcher
from pex.typing import TYPE_CHECKING
from pex.version import __version__

if PY2:
    from BaseHTTPServer import BaseHTTPRequestHandler
    from SocketServer import TCPServer
else:
    from http.server import BaseHTTPRequestHandler
    from socketserver import TCPServer

if TYPE_CHECKING:
    from typing import Iterator, Tuple


@pytest.fixture
def server_address():
    class GETRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = self.headers["User-Agent"].encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = TCPServer(("127.0.0.1", 0), GETRequestHandler)
    host, port = server.server_address

    server_thread = Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    try:
        yield host, port
    finally:
        server.shutdown()
        server_thread.join()


def test_user_agent(server_address):
    # type: (Tuple[str, int]) -> None

    host, port = server_address
    url = "http://{host}:{port}".format(host=host, port=port)
    url_fetcher = URLFetcher()
    with url_fetcher.get_body_stream(url) as fp:
        assert "pex/{version}".format(version=__version__) == fp.read().decode("utf-8")


EXPECTED_AUTHORIZATION = "Basic {credentials}".format(
    credentials=base64.b64encode(b"joe:bob").decode("ascii")
)


@pytest.fixture
def bearer_challenge_server_address():
    # type: () -> Iterator[Tuple[str, int]]

    class BearerChallengeRequestHandler(BaseHTTPRequestHandler):
        """Accepts basic auth but challenges with a scheme the stdlib cannot process.

        This mimics AWS CodeArtifact, which accepts basic auth credentials but answers
        unauthenticated requests with a 401 bearing `WWW-Authenticate: Bearer ...`.
        """

        def do_GET(self):
            if self.headers.get("Authorization") != EXPECTED_AUTHORIZATION:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Bearer realm="example"')
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            body = b"authorized"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = TCPServer(("127.0.0.1", 0), BearerChallengeRequestHandler)
    host, port = server.server_address

    server_thread = Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    try:
        yield host, port
    finally:
        server.shutdown()
        server_thread.join()


def test_preemptive_basic_auth_from_password_entries(bearer_challenge_server_address):
    # type: (Tuple[str, int]) -> None

    host, port = bearer_challenge_server_address
    url = "http://{host}:{port}/simple/foo/".format(host=host, port=port)
    url_fetcher = URLFetcher(
        password_entries=[
            PasswordEntry(
                machine=Machine.from_url(url),
                username="joe",
                password="bob",
            )
        ],
        netrc_file=None,
    )
    with url_fetcher.get_body_stream(url) as fp:
        assert b"authorized" == fp.read()


def test_preemptive_basic_auth_from_url_credentials(bearer_challenge_server_address):
    # type: (Tuple[str, int]) -> None

    host, port = bearer_challenge_server_address
    url = "http://joe:bob@{host}:{port}/simple/foo/".format(host=host, port=port)
    url_fetcher = URLFetcher(netrc_file=None)
    with url_fetcher.get_body_stream(url) as fp:
        assert b"authorized" == fp.read()


def test_unsupported_challenge_scheme_yields_http_error(bearer_challenge_server_address):
    # type: (Tuple[str, int]) -> None

    host, port = bearer_challenge_server_address
    url = "http://{host}:{port}/simple/foo/".format(host=host, port=port)
    url_fetcher = URLFetcher(
        password_entries=[
            # N.B.: These credentials are for another machine; so no preemptive auth applies and
            # the server's `WWW-Authenticate: Bearer` challenge is processed by the stdlib auth
            # handlers, which do not support the scheme.
            PasswordEntry(
                machine=Machine.from_url("https://other.example.com"),
                username="joe",
                password="bob",
            )
        ],
        netrc_file=None,
    )
    with pytest.raises(HTTPError) as exc_info:
        with url_fetcher.get_body_stream(url) as fp:
            fp.read()
    assert 401 == exc_info.value.code
