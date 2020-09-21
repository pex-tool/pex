"""Constants to enable safe imports from the `typing` library.

This file needs to exist because Pex still supports running from Python 2. The `typing` stdlib
module is new to Python 3, so runtime imports of it will fail.

We don't want to vendor `typing` because it adds to PEX's bootstrap time and its bundle size. It's
also tricky to get working robustly.

Instead, we leverage the fact that MyPy ships with type stubs for Python 2. We also use the special
`TYPE_CHECKING` value, which in production always evaluates to `False`, but when running MyPy,
evaluates to True. This allows us to safely import `typing` without it ever being used in
production.

Note that we only use type comments, rather than normal annotations, which is what allows us to
never need `typing` at runtime. (Exception for `cast`, see the below binding.)

To add type comments, use a conditional import like this:

    ```
    from pex.typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from typing import Optional, ...
    ```
"""

from __future__ import absolute_import

TYPE_CHECKING = False

# Unlike most type-hints, `cast` gets used at runtime. We define a no-op version for when
# TYPE_CHECKING is false.
if TYPE_CHECKING:
    from typing import cast as cast
else:

    def cast(type_, value):  # type: ignore[no-redef]
        return value
