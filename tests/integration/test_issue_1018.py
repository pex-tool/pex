# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.layout import Layout
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Iterable, List

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class EntryPointArgs(object):
    build_args = attr.ib(default=())  # type: Iterable[str]
    run_args = attr.ib(default=())  # type: Iterable[str]


@pytest.mark.parametrize(
    "execution_mode_args", [pytest.param([], id="PEX"), pytest.param(["--venv"], id="VENV")]
)
@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
@pytest.mark.parametrize(
    "entry_point_args",
    [
        pytest.param(EntryPointArgs(build_args=["-e", "issues_1018:main"]), id="ep-function"),
        pytest.param(EntryPointArgs(build_args=["-m", "issues_1018"]), id="ep-module"),
        pytest.param(EntryPointArgs(run_args=["-m", "issues_1018"]), id="no-ep"),
    ],
)
def test_execute_module_alter_sys(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
    layout,  # type: Layout.Value
    entry_point_args,  # type: EntryPointArgs
):
    # type: (...) -> None
    src_dir = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src_dir, "issues_1018.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import pickle

                def add(a, b):
                    return a + b

                def main():
                    pickle_add = pickle.dumps(add)
                    add_clone = pickle.loads(pickle_add)
                    print(add_clone(1, 2))

                if __name__ == "__main__":
                    main()
                """
            )
        )
    expected_output = b"3\n"

    # There are 18 ways we can invoke the module above using Pex corresponding to the 3D matrix with
    # axes: execution mode x layout x {entrypoint-function, entrypoint-module, ad-hoc (-m) module}.
    # We support all of these.

    pex_app = os.path.join(str(tmpdir), "app.pex")
    run_pex_command(
        args=["-D", src_dir, "-o", pex_app] + list(entry_point_args.build_args)
    ).assert_success()
    assert expected_output == subprocess.check_output(
        args=[pex_app] + list(entry_point_args.run_args)
    )
