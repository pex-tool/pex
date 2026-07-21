# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import base64
import json
import os.path
from threading import Thread

from pex.artifact_url import Fingerprint
from pex.auth import Machine, PasswordEntry
from pex.compatibility import PY2
from pex.fetcher import URLFetcher
from pex.requirements import parse_requirement_string
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.locked_resolve import LockStyle
from pex.resolve.locker import CredentialedURL, Credentials, Locker, Netloc
from pex.resolve.pep_691.api import Client
from pex.resolve.pep_691.fingerprint_service import FingerprintService
from pex.resolve.pep_691.model import Endpoint
from pex.resolve.resolved_requirement import PartialArtifact
from pex.targets import LocalInterpreter
from pex.typing import TYPE_CHECKING

if PY2:
    from BaseHTTPServer import BaseHTTPRequestHandler
    from SocketServer import TCPServer
else:
    from http.server import BaseHTTPRequestHandler
    from socketserver import TCPServer

if TYPE_CHECKING:
    from typing import Any, Optional


def test_credentials_redacted():
    # type: () -> None

    assert not Credentials("git").are_redacted()
    assert not Credentials("git", "").are_redacted()
    assert not Credentials("joe", "bob").are_redacted()

    assert Credentials("****").are_redacted()
    assert Credentials("joe", "****").are_redacted()


def test_basic_auth_rendering():
    # type: () -> None

    assert "git" == Credentials("git").render_basic_auth()
    assert "git:" == Credentials("git", "").render_basic_auth()
    assert "joe:bob" == Credentials("joe", "bob").render_basic_auth()


def test_host_port_rendering():
    # type: () -> None

    assert "example.com" == Netloc("example.com").render_host_port()
    assert "example.com:80" == Netloc("example.com", 80).render_host_port()


def test_strip_credentials():
    # type: () -> None

    def strip_credentials(
        url,  # type: str
        expected_credentials=None,  # type: Optional[Credentials]
    ):
        # type: (...) -> str
        credentialed_url = CredentialedURL.parse(url)
        assert expected_credentials == credentialed_url.credentials
        return str(credentialed_url.strip_credentials())

    assert "file:///a/file" == strip_credentials("file:///a/file")
    assert "http://example.com" == strip_credentials("http://example.com")
    assert "http://example.com:80" == strip_credentials("http://example.com:80")
    assert "http://example.com" == strip_credentials("http://joe@example.com", Credentials("joe"))
    assert "https://example.com:443" == strip_credentials(
        "https://joe@example.com:443", Credentials("joe")
    )
    assert "http://example.com" == strip_credentials(
        "http://joe:bob@example.com", Credentials("joe", "bob")
    )
    assert "phys://example.com:1137" == strip_credentials(
        "phys://joe:bob@example.com:1137", Credentials("joe", "bob")
    )
    assert "git://example.org" == strip_credentials("git://git@example.org", Credentials("git"))
    assert "git://example.org" == strip_credentials("git://****@example.org", Credentials("****"))


def test_inject_credentials():
    # type: () -> None

    def inject_credentials(
        url,  # type: str
        credentials,  # type: Optional[Credentials]
    ):
        # type: (...) -> str
        return str(CredentialedURL.parse(url).inject_credentials(credentials))

    assert "git://git@example.org" == inject_credentials("git://example.org", Credentials("git"))
    assert "git://git@example.org" == inject_credentials(
        "git://****@example.org", Credentials("git")
    )
    assert "http://joe:bob@example.org" == inject_credentials(
        "http://example.org", Credentials("joe", "bob")
    )
    assert "http://joe:bob@example.org" == inject_credentials(
        "http://joe:****@example.org", Credentials("joe", "bob")
    )


def test_pep_691_endpoint_authentication_and_fingerprinting(tmpdir):
    # type: (Any) -> None

    expected_authorization = "Basic {credentials}".format(
        credentials=base64.b64encode(b"joe:bob").decode("ascii")
    )
    unauthorized_requests = []

    class PEP691RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Authorization") != expected_authorization:
                unauthorized_requests.append(self.path)
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Bearer realm="example"')
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            body = json.dumps(
                {
                    "name": "foo",
                    "files": [
                        {
                            "filename": "foo-1.0.tar.gz",
                            "url": "../../files/foo-1.0.tar.gz",
                            "hashes": {"sha256": "strong"},
                        }
                    ],
                    "meta": {"api-version": "1.0"},
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.pypi.simple.v1+json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = TCPServer(("127.0.0.1", 0), PEP691RequestHandler)
    host, port = server.server_address
    endpoint_url = "http://{host}:{port}/simple/foo/".format(host=host, port=port)
    artifact_url = "http://{host}:{port}/files/foo-1.0.tar.gz".format(host=host, port=port)
    server_thread = Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    try:
        password_entry = PasswordEntry(
            machine=Machine.from_url(endpoint_url), username="joe", password="bob"
        )
        fingerprint_service = FingerprintService(
            api=Client(url_fetcher=URLFetcher(password_entries=[password_entry], netrc_file=None)),
            db_dir=os.path.join(str(tmpdir), "fingerprints"),
        )
        locker = Locker(
            target=LocalInterpreter.create(),
            root_requirements=[parse_requirement_string("foo")],
            resolver=ConfiguredResolver.default(),
            lock_style=LockStyle.UNIVERSAL,
            download_dir=os.path.join(str(tmpdir), "downloads"),
            fingerprint_service=fingerprint_service,
        )
        locker.analyze(
            "2026-07-21T00:00:00,000 Fetched page "
            "http://user:****@{host}:{port}/simple/foo/ as "
            "application/vnd.pypi.simple.v1+json".format(host=host, port=port)
        )

        endpoint = Endpoint(
            url=endpoint_url,
            content_type="application/vnd.pypi.simple.v1+json",
        )
        assert {endpoint} == locker._pep_691_endpoints
        assert [
            PartialArtifact(
                url=artifact_url,
                fingerprint=Fingerprint(algorithm="sha256", hash="strong"),
            )
        ] == list(
            fingerprint_service.fingerprint(
                endpoints=locker._pep_691_endpoints,
                artifacts=[PartialArtifact(url=artifact_url)],
            )
        )
        assert not unauthorized_requests, (
            "The real machine-scoped credentials should be sent preemptively after the credentials "
            "redacted by Pip are stripped from the logged endpoint."
        )
    finally:
        server.shutdown()
        server_thread.join()
