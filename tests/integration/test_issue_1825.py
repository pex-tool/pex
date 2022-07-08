# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os.path
import subprocess
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.orderedset import OrderedSet
from pex.testing import make_env, run_pex_command
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, List


DUMP_SYS_PATH_CODE = dedent(
    """\
    import json
    import sys


    json.dump(sys.path, sys.stdout)
    """
)


def create_sys_path_dump_pex(
    tmpdir,  # type: Any
    *additional_args  # type: str
):
    # type: (...) -> str

    exe = os.path.join(str(tmpdir), "exe.py")
    with open(exe, "w") as fp:
        fp.write(DUMP_SYS_PATH_CODE)

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(args=["--exe", exe, "-o", pex] + list(additional_args)).assert_success()
    return pex


def execute_sys_path_dump_pex(
    pex,  # type: str
    *additional_args,  # type: str
    **additional_env  # type: Any
):
    # type: (...) -> OrderedSet[str]

    return OrderedSet(
        os.path.realpath(entry)
        for entry in cast(
            "List[str]",
            json.loads(
                subprocess.check_output(
                    args=[pex] + list(additional_args), env=make_env(**additional_env)
                )
            ),
        )
    )


def read_additional_sys_path(
    pex,  # type: str
    *additional_args,  # type: str
    **additional_env  # type: Any
):
    # type: (...) -> List[str]

    isolated_sys_path = execute_sys_path_dump_pex(pex)
    return list(
        execute_sys_path_dump_pex(pex, *additional_args, **additional_env) - isolated_sys_path
    )


@pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--venv"], id="VENV"),
    ],
)
def test_pex_run_extra_sys_path(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex = create_sys_path_dump_pex(tmpdir, *execution_mode_args)

    foo = os.path.join(str(tmpdir), "foo")
    assert [foo] == read_additional_sys_path(pex, PEX_EXTRA_SYS_PATH=foo)

    other_exe = os.path.join(str(tmpdir), "other_exe.py")
    with safe_open(other_exe, "w") as fp:
        fp.write(DUMP_SYS_PATH_CODE)

    subprocess_proof = os.path.join(str(tmpdir), "proof")
    assert not os.path.exists(subprocess_proof)

    code = dedent(
        """\
        import subprocess
        import sys


        open({subprocess_proof!r}, "w").close()
        sys.exit(subprocess.call([sys.executable, {other_exe!r}]))
        """
    ).format(subprocess_proof=subprocess_proof, other_exe=other_exe)
    bar = os.path.join(str(tmpdir), "bar")
    assert bar in read_additional_sys_path(
        pex, "-c", code, PEX_INTERPRETER=1, PEX_EXTRA_SYS_PATH=bar
    )
    assert os.path.exists(subprocess_proof)
