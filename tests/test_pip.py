# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import warnings

from pex.interpreter import PythonInterpreter
from pex.pip import Pip
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import Any


def test_no_duplicate_constraints_pex_warnings(tmpdir):
    # type: (Any) -> None
    pex_root = os.path.join(str(tmpdir), "pex_root")
    pip_root = os.path.join(str(tmpdir), "pip_root")
    interpreter = PythonInterpreter.get()
    platform = interpreter.platform

    with ENV.patch(PEX_ROOT=pex_root), warnings.catch_warnings(record=True) as events:
        pip = Pip.create(path=pip_root, interpreter=interpreter)

    pip.spawn_debug(
        platform=platform.platform, impl=platform.impl, version=platform.version, abi=platform.abi
    ).wait()

    assert 0 == len([event for event in events if "constraints.txt" in str(event)]), (
        "Expected no duplicate constraints warnings to be emitted when creating a Pip venv but "
        "found\n{}".format("\n".join(map(str, events)))
    )
