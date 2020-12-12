# coding=utf-8
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from collections import namedtuple

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional


class NetworkConfiguration(
    namedtuple("NetworkConfiguration", ["retries", "timeout", "proxy", "cert", "client_cert"])
):
    """Configuration for network requests made by the resolver."""

    @classmethod
    def create(
        cls,
        retries=5,  # type: int
        timeout=15,  # type: float
        proxy=None,  # type: Optional[str]
        cert=None,  # type: Optional[str]
        client_cert=None,  # type: Optional[str]
    ):
        # type: (...) -> NetworkConfiguration
        """Create a network configuration accepting defaults for any values not explicitly provided.

        :param retries: The maximum number of retries each connection should attempt.
        :param timeout: The socket timeout in seconds.
        :param proxy: A proxy to use in the form [user:passwd@]proxy.server:port.
        :param cert: The path to an alternate CA bundle.
        :param client_cert: The path to an SSL client certificate which should be a single file
                                containing the private key and the certificate in PEM format.
        :return: The resulting network configuration.
        """
        assert retries >= 0, "The retries parameter should be >= 0; given: {}".format(retries)
        assert timeout >= 0, "The timeout parameter should be > 0; given: {}".format(timeout)

        return cls(
            retries=retries,
            timeout=timeout,
            proxy=proxy,
            cert=cert,
            client_cert=client_cert,
        )
