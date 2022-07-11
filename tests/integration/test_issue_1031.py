# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest

from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.testing import PY27, PY310, ensure_python_venv, make_env, run_simple_pex_test
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, MutableSet


@pytest.mark.parametrize(
    "py_version",
    [
        pytest.param(PY27, id="virtualenv-16.7.10"),
        pytest.param(PY310, id="pyvenv"),
    ],
)
def test_setuptools_isolation_with_system_site_packages(py_version):
    # type: (str) -> None
    system_site_packages_venv, _ = ensure_python_venv(
        py_version, latest_pip=False, system_site_packages=True
    )
    standard_venv, _ = ensure_python_venv(py_version, latest_pip=False, system_site_packages=False)

    print_sys_path_code = "import os, sys; print('\\n'.join(map(os.path.realpath, sys.path)))"

    def get_sys_path(python):
        # type: (str) -> MutableSet[str]
        _, stdout, _ = PythonInterpreter.from_binary(python).execute(
            args=["-c", print_sys_path_code]
        )
        return OrderedSet(stdout.strip().splitlines())

    system_site_packages_venv_sys_path = get_sys_path(system_site_packages_venv)
    standard_venv_sys_path = get_sys_path(standard_venv)

    def venv_dir(python):
        # type: (str) -> str
        bin_dir = os.path.dirname(python)
        venv_dir = os.path.dirname(bin_dir)
        return os.path.realpath(venv_dir)

    system_site_packages = {
        p
        for p in (system_site_packages_venv_sys_path - standard_venv_sys_path)
        if not p.startswith((venv_dir(system_site_packages_venv), venv_dir(standard_venv)))
    }
    assert len(system_site_packages) == 1, (
        "system_site_packages_venv_sys_path:\n"
        "\t{}\n"
        "standard_venv_sys_path:\n"
        "\t{}\n"
        "difference:\n"
        "\t{}".format(
            "\n\t".join(system_site_packages_venv_sys_path),
            "\n\t".join(standard_venv_sys_path),
            "\n\t".join(system_site_packages),
        )
    )
    system_site_packages_path = system_site_packages.pop()

    def get_system_site_packages_pex_sys_path(**env):
        # type: (**Any) -> MutableSet[str]
        output, returncode = run_simple_pex_test(
            body=print_sys_path_code,
            interpreter=PythonInterpreter.from_binary(system_site_packages_venv),
            env=make_env(**env),
        )
        assert returncode == 0
        return OrderedSet(output.decode("utf-8").strip().splitlines())

    assert system_site_packages_path not in get_system_site_packages_pex_sys_path()
    assert system_site_packages_path not in get_system_site_packages_pex_sys_path(
        PEX_INHERIT_PATH="false"
    )
    assert system_site_packages_path in get_system_site_packages_pex_sys_path(
        PEX_INHERIT_PATH="prefer"
    )
    assert system_site_packages_path in get_system_site_packages_pex_sys_path(
        PEX_INHERIT_PATH="fallback"
    )
