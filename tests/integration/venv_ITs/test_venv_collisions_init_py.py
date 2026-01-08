# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ast
import filecmp
import os.path
import subprocess

import pytest

from pex.compatibility import commonpath
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.venv.virtualenv import Virtualenv
from testing import IS_PYPY, PY_VER, make_env, run_pex_command
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(
    IS_PYPY or PY_VER < (3, 9) or PY_VER >= (3, 15),
    reason=(
        "The dbt libraries under test require Python>=3.9 and no wheels are published for PyPy or "
        "Python>=3.15."
    ),
)
def test_whitespace_only_init_py_collisions_avoided(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--pip-version",
            "latest-compatible",
            "dbt_adapters==1.9.0",
            "dbt_core==1.9.0b4",
            "--include-tools",
            "-o",
            pex,
        ]
    ).assert_success()

    distributions_by_project_name = {
        dist.project_name: dist.location for dist in PEX(pex).iter_distributions()
    }
    dbt_adapters_init_py = os.path.join(
        distributions_by_project_name[ProjectName("dbt_adapters")], "dbt", "__init__.py"
    )
    dbt_core_init_py = os.path.join(
        distributions_by_project_name[ProjectName("dbt_core")], "dbt", "__init__.py"
    )
    assert not filecmp.cmp(dbt_adapters_init_py, dbt_core_init_py, shallow=False)
    with open(dbt_adapters_init_py) as fp1, open(dbt_core_init_py) as fp2:
        # N.B.: ast.unparse exists in Python>=3.9, which this test is otherwise restricted to.
        assert ast.unparse(ast.parse(fp1.read(), fp1.name)) == ast.unparse(  # type: ignore[attr-defined]
            ast.parse(fp2.read(), fp2.name)
        )

    venv_dir = tmpdir.join("venv")
    subprocess.check_call(args=[pex, "venv", venv_dir], env=make_env(PEX_TOOLS=1))

    _, stdout, _ = Virtualenv(venv_dir).interpreter.execute(
        args=[
            "-c",
            "from dbt import adapters, version; print(adapters.__file__); print(version.__file__)",
        ]
    )
    paths = [venv_dir]
    paths.extend(path.strip() for path in stdout.splitlines())
    assert venv_dir == commonpath(paths)
