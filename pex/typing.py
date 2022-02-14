# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Constants to enable safe imports from the `typing` module.

This file needs to exist because Pex still supports running from Python 2. The `typing` stdlib
module is new to Python 3, so runtime imports of it will fail.

We don't want to vendor `typing` because it adds to PEX's bootstrap time and its bundle size. It's
also tricky to get working robustly.

Instead, we leverage the fact that MyPy ships with type stubs for Python 2. We also use the special
`TYPE_CHECKING` value, which in production always evaluates to `False`, but when running MyPy,
evaluates to True. This allows us to safely import `typing` without it ever being used in
production.

Note that we only use type comments, rather than normal annotations, which is what allows us to
never need `typing` at runtime except for `cast` and `overload` which have no-op runtime bindings
below.

To add type comments, use a conditional import like this:

    ```
    from pex.typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from typing import Optional, ...
    ```
"""

from __future__ import absolute_import, print_function

import sys

TYPE_CHECKING = False

# Unlike most type-hints, `cast` and `overload` get used at runtime. We define no-op versions for
# runtime use.
if TYPE_CHECKING:
    from typing import Any
    from typing import Generic as Generic
    from typing import cast as cast
    from typing import overload as overload

    if sys.version_info[:2] >= (3, 8):
        from typing import Literal as Literal
    else:
        from typing_extensions import Literal as Literal
else:

    def cast(_type, value):
        return value

    def overload(_func):
        def _never_called_since_structurally_shadowed(*_args, **_kwargs):
            raise NotImplementedError(
                "You should not call an overloaded function. A series of @overload-decorated "
                "functions outside a stub module should always be followed by an implementation "
                "that is not @overload-ed."
            )

        return _never_called_since_structurally_shadowed

    class _Generic(type):
        def __getitem__(cls, type_var):
            return cls

    if sys.version_info[0] == 2:

        class Generic(object):
            __metaclass__ = _Generic

    else:
        eval(compile("class Generic(object, metaclass=_Generic): pass", "<Generic>", "exec"))

    del _Generic

    Literal = {}
