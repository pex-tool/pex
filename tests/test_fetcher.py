# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

from threading import Thread

import pytest

from pex.compatibility import PY2
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
    from typing import Tuple


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
