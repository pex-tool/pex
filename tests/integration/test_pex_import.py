# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
from textwrap import dedent

import colors  # vendor:skip
import pytest

from pex import targets
from pex.cache.dirs import CacheDir
from pex.common import safe_open
from pex.layout import DEPS_DIR, Layout
from pex.resolve.pex_repository_resolver import resolve_from_pex
from pex.targets import Targets
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from pex.venv.virtualenv import Virtualenv
from testing import make_env, run_pex_command

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
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    empty_env_dir = os.path.join(str(tmpdir), "empty_env")
    empty_venv = Virtualenv.create(
        venv_dir=empty_env_dir,
    )
    empty_python = empty_venv.interpreter.binary

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
            # Add pex to verify that it will shadow bootstrap pex
            pex_project_dir,
            "-o",
            pex,
            "--layout",
            layout.value,
        ]
        + execution_mode_args,
    ).assert_success()

    def execute_with_pex_on_pythonpath(code):
        # type: (str) -> Text
        return (
            subprocess.check_output(
                args=[empty_python, "-c", code], env=make_env(PYTHONPATH=pex), cwd=str(tmpdir)
            )
            .decode("utf-8")
            .strip()
        )

    def get_third_party_prefix():
        if is_venv:
            return CacheDir.VENVS.path(pex_root=pex_root)
        elif layout is Layout.LOOSE:
            return os.path.join(pex, DEPS_DIR)
        else:
            return CacheDir.INSTALLED_WHEELS.path(pex_root=pex_root)

    # Verify 3rd party code can be imported hermetically from the PEX.
    alternate_pex_root = os.path.join(str(tmpdir), "alternate_pex_root")
    with ENV.patch(PEX_ROOT=alternate_pex_root):
        ambient_sys_path = [
            resolved_distribution.fingerprinted_distribution.distribution.location
            for resolved_distribution in resolve_from_pex(
                targets=Targets.from_target(targets.current()),
                pex=pex,
                requirements=["ansicolors==1.1.8"],
            ).distributions
        ]

    third_party_path = execute_with_pex_on_pythonpath(
        dedent(
            """\
            # Executor code like the AWS runtime.
            import sys

            sys.path = {ambient_sys_path!r} + sys.path

            # User code residing in the PEX.
            from __pex__ import colors

            print(colors.__file__)
            """.format(
                ambient_sys_path=ambient_sys_path
            )
        )
    )
    expected_prefix = get_third_party_prefix()
    assert third_party_path.startswith(
        expected_prefix
    ), "Expected 3rd party ansicolors path {path} to start with {expected_prefix}".format(
        path=third_party_path, expected_prefix=expected_prefix
    )

    # Verify 1st party code can be imported.
    first_party_path = execute_with_pex_on_pythonpath(
        "from __pex__ import first_party; print(first_party.__file__)"
    )
    if not is_venv and layout is Layout.LOOSE:
        assert os.path.join(pex, "first_party.py") == first_party_path
    else:
        expected_cache_type = CacheDir.VENVS if is_venv else CacheDir.UNZIPPED_PEXES
        assert first_party_path.startswith(
            expected_cache_type.path(pex_root=pex_root)
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

    # Verify bootstrap code does not leak attrs from vendored code
    assert "no leak" == execute_with_pex_on_pythonpath(
        dedent(
            """\
            import __pex__

            try:
                import attr
                print(attr.__file__)
            except ImportError:
                print("no leak")
            """
        )
    )

    # Verify bootstrap pex code is demoted to the end of `sys.path`
    assert os.path.join(pex, ".bootstrap") == execute_with_pex_on_pythonpath(
        dedent(
            """\
            import __pex__
            import sys
            print(sys.path[-1])
            """
        )
    )

    # Verify third party pex shadows bootstrap pex
    pex_third_party_path = execute_with_pex_on_pythonpath(
        dedent(
            """\
            import __pex__
            import pex
            print(pex.__file__)
            """
        )
    )

    assert pex_third_party_path.startswith(get_third_party_prefix())
