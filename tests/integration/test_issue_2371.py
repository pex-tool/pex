# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess
import sys
from collections import defaultdict
from textwrap import dedent

import pytest

from pex.compatibility import commonpath
from pex.dist_metadata import ProjectNameAndVersion
from pex.interpreter import PythonInterpreter
from pex.pep_503 import ProjectName
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing import PY310, PY311, ensure_python_interpreter, run_pex_command
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import DefaultDict, List, Text


@pytest.mark.skipif(sys.version_info[:2] < (3, 6), reason="p537 is only available for Python>=3.6.")
def test_venv_repository_multiplatform_resolve(tmpdir):
    # type: (Tempdir) -> None

    other_interpreter = (
        ensure_python_interpreter(PY311)
        if sys.version_info[:2] == (3, 10)
        else ensure_python_interpreter(PY310)
    )

    def create_p537_venv(
        python,  # type: str
        install_cowsay,  # type: bool
    ):
        # type: (...) -> str
        interpreter = PythonInterpreter.from_binary(python)
        venv_dir = tmpdir.join(
            "venv-{major}.{minor}".format(
                major=interpreter.version[0], minor=interpreter.version[1]
            )
        )
        venv = Virtualenv.create(
            venv_dir=venv_dir, interpreter=interpreter, install_pip=InstallationChoice.YES
        )
        requirements = ["p537", "ansicolors"]
        if install_cowsay:
            requirements.append("cowsay")
        subprocess.check_call(args=[venv.interpreter.binary, "-m", "pip", "install"] + requirements)
        return venv_dir

    venv1 = create_p537_venv(sys.executable, install_cowsay=True)
    venv2 = create_p537_venv(other_interpreter, install_cowsay=False)

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--venv-repository",
            venv1,
            "--venv-repository",
            venv2,
            "p537",
            "ansicolors",
            "cowsay; python_version == '{major}.{minor}'".format(
                major=sys.version_info[0], minor=sys.version_info[1]
            ),
            "-o",
            pex,
        ]
    ).assert_success()

    distributions_by_project_name = defaultdict(list)  # type: DefaultDict[ProjectName, List[str]]
    for distribution in PexInfo.from_pex(pex).distributions:
        pnav = ProjectNameAndVersion.from_filename(distribution)
        distributions_by_project_name[pnav.canonicalized_project_name].append(distribution)
    assert 2 == len(distributions_by_project_name.pop(ProjectName("p537")))
    assert 1 == len(distributions_by_project_name.pop(ProjectName("ansicolors")))
    assert 1 == len(distributions_by_project_name.pop(ProjectName("cowsay")))
    assert not distributions_by_project_name

    def assert_greet(
        python,  # type: str
        expect_cowsay,  # type: bool
    ):
        # type: (...) -> Text
        process = subprocess.Popen(
            args=[
                python,
                pex,
                "-c",
                dedent(
                    """\
                    from __future__ import print_function
                    import sys

                    import p537

                    try:
                        import cowsay
                    except ImportError:
                        if {expect_cowsay!r}:
                            raise


                    p537.greet()
                    print(p537.__file__, file=sys.stderr)
                    """
                ).format(expect_cowsay=expect_cowsay),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate()
        assert 0 == process.returncode
        assert b"Hello World!" == stdout
        module_path = stderr.decode("utf-8").strip()
        assert pex_root == commonpath((pex_root, module_path))
        return module_path

    p537_module_path = assert_greet(sys.executable, expect_cowsay=True)
    other_p537_module_path = assert_greet(other_interpreter, expect_cowsay=False)
    assert p537_module_path != other_p537_module_path
