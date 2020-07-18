# coding=utf-8
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from collections import namedtuple


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
        cache_ttl=3600,
        retries=5,
        timeout=15,
        headers=None,
        proxy=None,
        cert=None,
        client_cert=None,
    ):
        """Creates a new network configuration accepting defaults for any values not explicitly
        provided.

        :param int cache_ttl: The maximum time an item is retained in the HTTP cache in seconds.
        :param int retries: The maximum number of retries each connection should attempt.
        :param timeout: The socket timeout in seconds.
        :param headers: A list of additional HTTP headers to send in the form NAME:VALUE.
        :type headers: list of str
        :param str proxy: A proxy to use in the form [user:passwd@]proxy.server:port.
        :param str cert: The path to an alternate CA bundle.
        :param str client_cert: The path to an SSL client certificate which should be a single file
                                containing the private key and the certificate in PEM format.
        :return: The resulting network configuration.
        :rtype: :class:`NetworkConfiguration`
        """
        assert cache_ttl >= 0, "The cache_ttl parameter should be >= 0; given: {}".format(cache_ttl)
        assert retries >= 0, "The retries parameter should be >= 0; given: {}".format(retries)
        assert timeout >= 0, "The timeout parameter should be > 0; given: {}".format(timeout)
        return cls(
            cache_ttl=cache_ttl,
            retries=retries,
            timeout=timeout,
            headers=tuple(headers or ()),
            proxy=proxy,
            cert=cert,
            client_cert=client_cert,
        )
