# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from ..tracer import Tracer

__all__ = ('TRACER',)

TRACER = Tracer(predicate=Tracer.env_filter('PEX_HTTP'), prefix='pex.http: ')
