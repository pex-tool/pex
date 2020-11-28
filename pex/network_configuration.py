# coding=utf-8
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from collections import namedtuple

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, Iterable, Optional


class NetworkConfiguration(
    namedtuple(
        "NetworkConfiguration",
        ["cache_ttl", "retries", "timeout", "headers", "proxy", "cert", "client_cert"],
    )
):
    """Configuration for network requests made by the resolver."""

    @classmethod
    def create(
        cls,
        cache_ttl=3600,  # type: float
        retries=5,  # type: int
        timeout=15,  # type: float
        headers=None,  # type: Optional[Iterable[str]]
        proxy=None,  # type: Optional[str]
        cert=None,  # type: Optional[str]
        client_cert=None,  # type: Optional[str]
    ):
        # type: (...) -> NetworkConfiguration
        """Create a network configuration accepting defaults for any values not explicitly provided.

        :param cache_ttl: The maximum time an item is retained in the HTTP cache in seconds.
        :param retries: The maximum number of retries each connection should attempt.
        :param timeout: The socket timeout in seconds.
        :param headers: A list of additional HTTP headers to send in the form NAME:VALUE.
        :param proxy: A proxy to use in the form [user:passwd@]proxy.server:port.
        :param cert: The path to an alternate CA bundle.
        :param client_cert: The path to an SSL client certificate which should be a single file
                                containing the private key and the certificate in PEM format.
        :return: The resulting network configuration.
        """
        assert cache_ttl >= 0, "The cache_ttl parameter should be >= 0; given: {}".format(cache_ttl)
        assert retries >= 0, "The retries parameter should be >= 0; given: {}".format(retries)
        assert timeout >= 0, "The timeout parameter should be > 0; given: {}".format(timeout)
        if headers:
            bad_headers = [header for header in headers if ":" not in header]
            assert not bad_headers, (
                "The following headers were malformed:\n"
                "{bad_headers}\n"
                "All headers must be of the form NAME:VALUE.".format(
                    bad_headers="\n".join(bad_headers),
                )
            )

        return cls(
            cache_ttl=cache_ttl,
            retries=retries,
            timeout=timeout,
            headers=tuple(headers or ()),
            proxy=proxy,
            cert=cert,
            client_cert=client_cert,
        )

    def headers_as_dict(self):
        # type: () -> Dict[str, str]
        return dict(header.split(":", 1) for header in self.headers)
