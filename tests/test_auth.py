# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.auth import Machine, PasswordDatabase, PasswordEntry


def test_password_database_lookup_matches_machine():
    # type: () -> None

    example = PasswordEntry(
        machine=Machine.from_url("https://example.com"), username="joe", password="bob"
    )
    example_alt_port = PasswordEntry(
        machine=Machine.from_url("https://example.com:8443"), username="jane", password="bib"
    )
    database = PasswordDatabase(entries=(example, example_alt_port))

    assert example == database.lookup("https://example.com/simple/foo/")
    assert example_alt_port == database.lookup("https://example.com:8443/simple/foo/")
    assert database.lookup("https://other.example.com/simple/foo/") is None


def test_password_database_lookup_prefers_later_entries():
    # type: () -> None

    machine = Machine.from_url("https://example.com")
    netrc = PasswordEntry(machine=machine, username="joe", password="stale")
    configured = PasswordEntry(machine=machine, username="joe", password="current")

    database = PasswordDatabase(entries=(netrc,)).append((configured,))

    assert configured == database.lookup("https://example.com/simple/foo/"), (
        "Credentials from explicit configuration appended to the password database should take "
        "precedence over earlier netrc credentials for the same machine."
    )


def test_password_database_lookup_ignores_default_entries():
    # type: () -> None

    default = PasswordEntry(username="joe", password="bob")
    database = PasswordDatabase(entries=(default,))

    assert database.lookup("https://example.com/simple/foo/") is None, (
        "The credentials of a machine-less `default` netrc entry should not be offered for "
        "preemptive use against arbitrary hosts."
    )


def test_password_database_lookup_unparseable_url():
    # type: () -> None

    database = PasswordDatabase(
        entries=(
            PasswordEntry(
                machine=Machine.from_url("https://example.com"), username="joe", password="bob"
            ),
        )
    )

    assert database.lookup("not-a-url") is None
