# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
import sys
from textwrap import dedent

import colors
import pytest

from pex.common import safe_open
from pex.layout import DEPS_DIR, Layout
from pex.testing import IS_PYPY, PY27, PY_VER, ensure_python_interpreter, make_env, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, List, Text


@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
@pytest.mark.parametrize(
    "execution_mode_args", [pytest.param([], id="UNZIPPED"), pytest.param(["--venv"], id="VENV")]
)
def test_import_from_pex(
    tmpdir,  # type: Any
    layout,  # type: Layout.Value
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    # For CPython 2.7 we work around bad virtualenvs created by tox that lead to the following
    # error by using a pyenv CPython 2.7 interpreter instead:
    #
    # Traceback (most recent call last):
    #   File "<string>", line 1, in <module>
    #   File "/tmp/pytest-of-jsirois/pytest-10/popen-gw5/test_import_from_pex_UNZIPPED_0/importable.pex/.bootstrap/pex/third_party/__init__.py", line 39, in load_module
    #   File "/home/jsirois/.pyenv/versions/2.7.18/lib/python2.7/importlib/__init__.py", line 37, in import_module
    #     __import__(name)
    #   File "/home/jsirois/dev/pantsbuild/jsirois-pex/.tox/py27-integration/lib/python2.7/site-packages/_virtualenv.py", line 112, in find_module
    #     if fullname in _DISTUTILS_PATCH:
    # TypeError: argument of type 'NoneType' is not iterable
    python = ensure_python_interpreter(PY27) if (2, 7) == PY_VER and not IS_PYPY else sys.executable

    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "first_party.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import colors


                def warn(msg):
                    print(colors.yellow(msg))
                """
            )
        )

    pex_root = os.path.join(str(tmpdir), "pex_root")
    pex = os.path.join(str(tmpdir), "importable.pex")
    is_venv = "--venv" in execution_mode_args

    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "-D",
            src,
            "ansicolors==1.1.8",
            "-o",
            pex,
            "--layout",
            layout.value,
        ]
        + execution_mode_args,
        python=python,
    ).assert_success()

    def execute_with_pex_on_pythonpath(code):
        # type: (str) -> Text
        return (
            subprocess.check_output(args=[python, "-c", code], env=make_env(PYTHONPATH=pex))
            .decode("utf-8")
            .strip()
        )

    # Verify 3rd party code can be imported.
    third_party_path = execute_with_pex_on_pythonpath(
        "from __pex__ import colors; print(colors.__file__)"
    )
    if is_venv:
        expected_prefix = os.path.join(pex_root, "venvs")
    elif layout is Layout.LOOSE:
        expected_prefix = os.path.join(pex, DEPS_DIR)
    else:
        expected_prefix = os.path.join(pex_root, "installed_wheels")
    assert third_party_path.startswith(
        expected_prefix
    ), "Expected 3rdp party ansicolors path {path} to start with {expected_prefix}".format(
        path=third_party_path, expected_prefix=expected_prefix
    )

    # Verify 1st party code can be imported.
    first_party_path = execute_with_pex_on_pythonpath(
        "from __pex__ import first_party; print(first_party.__file__)"
    )
    if not is_venv and layout is Layout.LOOSE:
        assert os.path.join(pex, "first_party.py") == first_party_path
    else:
        expected_prefix = os.path.join(pex_root, "venvs" if is_venv else "unzipped_pexes")
        assert first_party_path.startswith(
            expected_prefix
        ), "Expected 1st party first_party.py path {path} to start with {expected_prefix}".format(
            path=first_party_path, expected_prefix=expected_prefix
        )

    # Verify a single early import of __pex__ allows remaining imports to be "normal".
    assert "\n".join((colors.blue("42"), colors.yellow("Vogon"))) == execute_with_pex_on_pythonpath(
        dedent(
            """\
            import __pex__

            import colors
            import first_party
            
            
            print(colors.blue("42"))
            first_party.warn("Vogon")
            """
        )
    )
