"""
This description was taken from the pip source code and slightly modified: see
https://github.com/pantsbuild/pex/blob/2783d304daf43dc1d59753c7e5fc2599b16acd01/pex/vendor/_vendored/pip/pip/_internal/utils/typing.py.

`mypy` - the static type analysis tool we use - uses the `typing` module, which
provides core functionality fundamental to mypy's functioning.
Generally, `typing` would be imported at runtime and used in that fashion -
it acts as a no-op at runtime and does not have any run-time overhead by
design.

We actually still can't have `typing` imported at runtime, even though all of its entries in the
module are no-ops, because the process of importing `typing` would cause pex bootstrap time to
regress, which is a metric we've worked very hard to reduce. typing is available in python 2 and 3,
but mypy already contains those stubs for python 3, and for python 2 with the --py2 flag.

To work around this, mypy allows the typing import to be behind a False-y
optional to prevent it from running at runtime and type-comments can be used
to remove the need for the types to be accessible directly during runtime.
This module provides the False-y guard in a nicely named fashion so that a
curious maintainer can reach here to read this.

In pex, all static-typing related imports should be guarded as follows:
    from pex.typing import MYPY_CHECK_RUNNING
    if MYPY_CHECK_RUNNING:
        from pex.typing import ...

Ref: https://github.com/python/mypy/issues/3216
"""

from __future__ import absolute_import

# We first try to re-export from the std lib for Python 3. If that fails, we're on Python 2 so used
# the vendored `typing` backport. Note that this backport is specific to Python 2.

MYPY_CHECK_RUNNING = False

# mypy: implicit-reexport
if MYPY_CHECK_RUNNING:
    from typing import cast
else:
    # typing's cast() is needed at runtime, but we don't want to import typing.
    # Thus, we use a dummy no-op version, which we tell mypy to ignore.
    def cast(type_, value):  # type: ignore[no-redef]
        return value
