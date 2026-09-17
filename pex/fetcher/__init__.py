# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.fetcher.ssl import initialize_ssl_context
from pex.fetcher.url import URLFetcher

__all__ = ["URLFetcher", "initialize_ssl_context"]
