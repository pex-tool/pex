# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.resolve.locker import CredentialedURL, Credentials, Netloc
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional


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
