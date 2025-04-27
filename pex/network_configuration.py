# coding=utf-8
# Copyright 2020 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class NetworkConfiguration(object):
    """Configuration for network requests made by the resolver.

    :param retries: The maximum number of retries each connection should attempt.
    :param resume_retries: The maximum number of attempts to resume or restart an incomplete
                           download.
    :param timeout: The socket timeout in seconds.
    :param proxy: A proxy to use in the form [user:passwd@]proxy.server:port.
    :param cert: The path to an alternate CA bundle.
    :param client_cert: The path to an SSL client certificate which should be a single file
                        containing the private key and the certificate in PEM format.
    :return: The resulting network configuration.
    """

    retries = attr.ib(default=5)  # type: int
    resume_retries = attr.ib(default=3)  # type: int
    timeout = attr.ib(default=15)  # type: float
    proxy = attr.ib(default=None)  # type: Optional[str]
    cert = attr.ib(default=None)  # type: Optional[str]
    client_cert = attr.ib(default=None)  # type: Optional[str]

    @retries.validator
    @resume_retries.validator
    def _validate_gte_zero(self, attribute, value):
        if value < 0:
            raise ValueError(
                "The {} parameter should be >= 0; given: {}".format(attribute.name, value)
            )

    @timeout.validator
    def _validate_gt_zero(self, attribute, value):
        if value <= 0:
            raise ValueError(
                "The {} parameter should be > 0; given: {}".format(attribute.name, value)
            )
