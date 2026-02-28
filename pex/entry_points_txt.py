# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import itertools
import os
from textwrap import dedent

from pex import windows
from pex.common import safe_open
from pex.dist_metadata import CallableEntryPoint, EntryPoints
from pex.exceptions import reportable_unexpected_error_msg
from pex.executables import chmod_plus_x
from pex.interpreter import PythonInterpreter
from pex.os import WINDOWS
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterator, Optional, Text, Tuple


def install_scripts(
    dest_dir,  # type: str
    entry_points,  # type: EntryPoints
    interpreter=None,  # type: Optional[PythonInterpreter]
    overwrite=True,  # type: bool
    hermetic_scripts=False,  # type: bool
):
    # type: (...) -> Iterator[Tuple[Text, Text]]

    if not entry_points:
        return

    if entry_points.source is None:
        raise AssertionError(reportable_unexpected_error_msg())

    script_src = entry_points.source
    if interpreter:
        shebang = interpreter.shebang(args=interpreter.hermetic_args if hermetic_scripts else None)
    else:
        shebang = "#!python"
    for named_entry_point, gui in itertools.chain.from_iterable(
        ((value, gui) for value in entry_points.get(key, {}).values())
        for key, gui in (("console_scripts", False), ("gui_scripts", True))
    ):
        entry_point = named_entry_point.entry_point
        if isinstance(entry_point, CallableEntryPoint):
            script = dedent(
                """\
                {shebang}
                # -*- coding: utf-8 -*-
                import importlib
                import sys

                entry_point = importlib.import_module({modname!r})
                for attr in {attrs!r}:
                    entry_point = getattr(entry_point, attr)

                if __name__ == "__main__":
                    import os
                    pex_root_fallback = os.environ.get("_PEX_ROOT_FALLBACK")
                    if pex_root_fallback:
                        import atexit
                        import shutil

                        atexit.register(shutil.rmtree, pex_root_fallback, True)

                    sys.exit(entry_point())
                """
            ).format(shebang=shebang, modname=entry_point.module, attrs=entry_point.attrs)
        else:
            script = dedent(
                """\
                {shebang}
                # -*- coding: utf-8 -*-
                import runpy
                import sys

                if __name__ == "__main__":
                    import os
                    pex_root_fallback = os.environ.get("_PEX_ROOT_FALLBACK")
                    if pex_root_fallback:
                        import atexit
                        import shutil

                        atexit.register(shutil.rmtree, pex_root_fallback, True)

                    runpy.run_module({modname!r}, run_name="__main__", alter_sys=True)
                    sys.exit(0)
                """
            ).format(shebang=shebang, modname=entry_point.module)
        script_abspath = os.path.join(dest_dir, named_entry_point.name)
        if WINDOWS:
            script_abspath = windows.create_script(
                script_abspath, script, gui=gui, overwrite=overwrite
            )
        elif overwrite or not os.path.exists(script_abspath):
            with safe_open(script_abspath, "w") as fp:
                fp.write(script)
            chmod_plus_x(fp.name)
        yield script_src, script_abspath
