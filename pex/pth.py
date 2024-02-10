# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import sys

from pex.compatibility import PY2, exec_function
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterator


def iter_pth_paths(filename):
    # type: (str) -> Iterator[str]
    """Given a .pth file, extract and yield all inner paths without honoring imports.

    This shadows Python's site.py behavior, which is invoked at interpreter startup.
    """
    try:
        f = open(filename, "rU" if PY2 else "r")  # noqa
    except IOError:
        return

    seen = set()
    with f:
        for i, line in enumerate(f, start=1):
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            elif line.startswith(("import ", "import\t")):
                # One important side effect of executing import lines can be alteration of the
                # sys.path directly or indirectly as a programmatic way to add sys.path entries
                # in contrast to the standard .pth mechanism of including fixed paths as
                # individual lines in the file. Here we capture all such programmatic attempts
                # to expand the sys.path and report the additions.
                original_sys_path = sys.path[:]
                try:
                    # N.B.: Setting sys.path to empty is ok since all the .pth files we find and
                    # execute have already been found and executed by our ambient sys.executable
                    # when it started up before running this PEX file. As such, all symbols imported
                    # by the .pth files then will still be available now as cached in sys.modules.
                    sys.path = []
                    exec_function(line, globals_map={})
                    for path in sys.path:
                        norm_path = os.path.normcase(path)
                        if norm_path not in seen:
                            yield path
                            seen.add(norm_path)
                except Exception as e:
                    # NB: import lines are routinely abused with extra code appended using `;` so
                    # the class of exceptions that might be raised in broader than ImportError. As
                    # such we catch broadly here.
                    TRACER.log(
                        "Error executing line {linenumber} of {pth_file} with content:\n"
                        "{content}\n"
                        "Error was:\n"
                        "{error}".format(linenumber=i, pth_file=filename, content=line, error=e),
                        V=9,
                    )

                    # Defer error handling to the higher level site.py logic invoked at startup.
                    return
                finally:
                    sys.path = original_sys_path
            else:
                extras_dir = os.path.abspath(os.path.join(os.path.dirname(filename), line))
                norm_extras_dir = os.path.normcase(extras_dir)
                if norm_extras_dir not in seen and os.path.exists(extras_dir):
                    yield extras_dir
                    seen.add(norm_extras_dir)
