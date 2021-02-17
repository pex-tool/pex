# coding=utf-8
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import Optional
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class NetworkConfiguration(object):
    """Configuration for network requests made by the resolver.

    :param retries: The maximum number of retries each connection should attempt.
    :param timeout: The socket timeout in seconds.
    :param proxy: A proxy to use in the form [user:passwd@]proxy.server:port.
    :param cert: The path to an alternate CA bundle.
    :param client_cert: The path to an SSL client certificate which should be a single file
                        containing the private key and the certificate in PEM format.
    :return: The resulting network configuration.
    """

    retries = attr.ib(default=5)  # type: int
    timeout = attr.ib(default=15)  # type: float
    proxy = attr.ib(default=None)  # type: Optional[str]
    cert = attr.ib(default=None)  # type: Optional[str]
    client_cert = attr.ib(default=None)  # type: Optional[str]

    @retries.validator
    def _validate_retries(self, attribute, value):
        if value < 0:
            raise ValueError(
                "The {} parameter should be >= 0; given: {}".format(attribute.name, value)
            )

    @timeout.validator
    def _validate_timeout(self, attribute, value):
        if value <= 0:
            raise ValueError(
                "The {} parameter should be > 0; given: {}".format(attribute.name, value)
            )
