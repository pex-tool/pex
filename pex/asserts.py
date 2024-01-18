# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import platform
import sys
from textwrap import dedent

from pex.version import __version__

_ASSERT_ADVICE = (
    dedent(
        """\
    The error reported above resulted from an unexpected programming error which 
    you should never encounter.
    
    Firstly, please accept our apology!
    
    If you could file an issue with the error above and the details below, we'd be
    grateful. You can do that at https://github.com/pantsbuild/pex/issues/new and
    redact or amend any details that expose sensitive information:
    ---
    Pex {version}
    platform: {platform}
    python: {python_version}
    argv: {argv}
    """
    )
    .format(
        version=__version__, platform=platform.platform(), python_version=sys.version, argv=sys.argv
    )
    .strip()
)


def production_assert(condition, message=""):
    # type: (...) -> None

    if condition:
        return

    assert_advice = _ASSERT_ADVICE
    pex = os.environ.get("PEX")
    if pex:
        try:
            import json

            from pex.pex_info import PexInfo

            pex_info = PexInfo.from_pex(pex)
            pex_info.update(PexInfo.from_env())
            assert_advice = "\n".join(
                (assert_advice, "PEX-INFO:", json.dumps(pex_info.as_json_dict(), indent=2))
            )
        except Exception:
            pass

    raise AssertionError("\n".join((message, "---", assert_advice)))
