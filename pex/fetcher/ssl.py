# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import contextlib
import os
import sys
import threading
from contextlib import contextmanager

from pex.compatibility import in_main_thread
from pex.exceptions import production_assert
from pex.network_configuration import NetworkConfiguration
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ssl import SSLContext
    from typing import Dict, Iterator, Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@contextmanager
def guard_stdout():
    # type: () -> Iterator[None]
    # Under PyPy 3.9 and 3.10, `ssl.create_default_context` causes spurious informational text about
    # SSL certs to be emitted to stdout; so we squelch this.
    if hasattr(sys, "pypy_version_info") and sys.version_info[:2] >= (3, 9):
        with open(os.devnull, "w") as fp:
            # The `contextlib.redirect_stdout` function is available for Python 3.4+.
            with contextlib.redirect_stdout(fp):  # type: ignore[attr-defined]
                yield
    else:
        yield


@attr.s(frozen=True)
class _CertConfig(object):
    @classmethod
    def create(cls, network_configuration=None):
        # type: (Optional[NetworkConfiguration]) -> _CertConfig
        if network_configuration is None:
            return cls()
        return cls(cert=network_configuration.cert, client_cert=network_configuration.client_cert)

    cert = attr.ib(default=None)  # type: Optional[str]
    client_cert = attr.ib(default=None)  # type: Optional[str]

    def create_ssl_context(self):
        # type: () -> SSLContext

        # These shenanigans deserve some explanation, since, in OpenSSL 3.0 anyhow, it is perfectly
        # fine to create an SSL Context (`SSL_CTX_new`) in any thread:
        #
        # It turns out that, in typical use, the CPython ssl module hides OpenSSL configuration
        # issues through no real fault of its own. This is due to the fact that an import of the
        # `ssl` module, which generally happens in the main thread, triggers, through instantiation
        # of the `ssl.Purpose` enum type [^1] a call to OpenSSL's `OBJ_obj2nid` [^2][^3] which
        # loads OpenSSL config but throws away the return value; thus hiding errors in config. Since
        # the OpenSSL config scheme is to load it at most once per thread, this means subsequent
        # OpenSSL call paths in the same thread that imported `ssl` (like the one generated via
        # `ssl.create_default_context`) that _do_ check the return value of config loading [^4][^5],
        # will not have to load config (since it's been done once already in the thread) and thus
        # will not get the chance to check the config load function return value and will thus not
        # error. This default behavior is almost certainly bad, since it allows invalid OpenSSL
        # configs to go partially read at best. That said, this is the default Python
        # single-threaded behavior and, right or wrong, we preserve that here by forcing our SSL
        # initialization to happen in the main thread, keeping any OpenSSL misconfiguration silently
        # ignored.
        #
        # The only solace here is that the use cases where OpenSSL config can be bad on a machine
        # and the machine still function are narrow. The case we know of, that triggered creation of
        # this machinery, involves the combination of a modern PBS Python [^6] (which has a vanilla
        # OpenSSL statically linked into the Python binary) running on a RedHat OS that expresses
        # custom RedHat configuration keys [^7] in its OpenSSL config. These custom keys are only
        # supported by RedHat patches to OpenSSL and cause vanilla versions of OpenSSL to error when
        # loading config due to unknown configuration options.
        #
        # [^1]: https://github.com/python/cpython/blob/5a173efa693a053bf4a059c82c1c06c82a9fa8fb/Lib/ssl.py#L394-L419
        # [^2]: https://github.com/python/cpython/blob/5a173efa693a053bf4a059c82c1c06c82a9fa8fb/Modules/_ssl.c#L5534-L5552
        # [^3]: https://github.com/openssl/openssl/blob/c3cc0f1386b0544383a61244a4beeb762b67498f/crypto/objects/obj_dat.c#L326-L340
        # [^4]: https://github.com/openssl/openssl/blob/c3cc0f1386b0544383a61244a4beeb762b67498f/ssl/ssl_lib.c#L3194-L3212
        # [^5]: https://github.com/openssl/openssl/blob/c3cc0f1386b0544383a61244a4beeb762b67498f/ssl/ssl_init.c#L86-L116
        # [^6]: https://github.com/astral-sh/python-build-standalone/releases/tag/20240107
        # [^7]: https://gitlab.com/redhat-crypto/fedora-crypto-policies/-/merge_requests/110/diffs#269a48e71ac25ad1d07ff00db2390834c8ba7596_11_16
        production_assert(
            in_main_thread(),
            "An SSLContext must be initialized from the main thread. An attempt was made to "
            "initialize an SSLContext for {cert_config} from thread {thread}.",
            cert_config=self,
            thread=threading.current_thread(),
        )
        with guard_stdout():
            # We import ssl lazily as an affordance to PEXes that use gevent SSL monkeypatching,
            # which requires (and checks) that the `ssl` module is not imported priory to the
            # `from gevent import monkey; monkey.patch_all()` call.
            #
            # See: https://github.com/pex-tool/pex/issues/2415
            import ssl

            ssl_context = ssl.create_default_context(cafile=self.cert)
            if self.client_cert:
                ssl_context.load_cert_chain(self.client_cert)
            return ssl_context


_SSL_CONTEXTS = {}  # type: Dict[_CertConfig, SSLContext]


def get_ssl_context(network_configuration=None):
    # type: (Optional[NetworkConfiguration]) -> SSLContext
    cert_config = _CertConfig.create(network_configuration=network_configuration)
    ssl_context = _SSL_CONTEXTS.get(cert_config)
    if not ssl_context:
        ssl_context = cert_config.create_ssl_context()
        _SSL_CONTEXTS[cert_config] = ssl_context
    return ssl_context


def initialize_ssl_context(network_configuration=None):
    # type: (Optional[NetworkConfiguration]) -> None
    get_ssl_context(network_configuration=network_configuration)


# N.B.: We eagerly initialize an SSLContext for the default case of no CA cert and no client cert.
# When a custom CA cert or client cert or both are configured, that code will need to call
# initialize_ssl_context on its own.
initialize_ssl_context()
