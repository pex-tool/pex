# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.typing import TYPE_CHECKING
from testing import make_env, run_pex_command, subprocess

if TYPE_CHECKING:
    from typing import Any, List


@pytest.mark.parametrize(
    ["boot_args"],
    [
        pytest.param([], id="__main__.py boot"),
        pytest.param(["--sh-boot"], id="--sh-boot"),
    ],
)
def test_venv_pex_script_non_hermetic(
    tmpdir,  # type: Any
    boot_args,  # type: List[str]
):
    # type: (...) -> None

    # A console script that injects an element in the PYTHONPATH.
    ot_simulator_src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(ot_simulator_src, "ot_simulator.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import os
                import subprocess
                import sys

                def run():
                    pythonpath = ["injected"]
                    existing_pythonpath = os.environ.get("PYTHONPATH")
                    if existing_pythonpath:
                        pythonpath.extend(existing_pythonpath.split(os.pathsep))
                    os.environ["PYTHONPATH"] = os.pathsep.join(pythonpath)

                    sys.exit(subprocess.call(sys.argv[1:]))
                """
            )
        )
    with safe_open(os.path.join(ot_simulator_src, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = ot-simulator
                version = 0.0.1

                [options]
                py_modules =
                    ot_simulator

                [options.entry_points]
                console_scripts =
                    instrument = ot_simulator:run
                """
            )
        )
    with safe_open(os.path.join(ot_simulator_src, "setup.py"), "w") as fp:
        fp.write("from setuptools import setup; setup()")

    # An entrypoint that can observe the PYTHONPATH / sys.path.
    app = os.path.join(str(tmpdir), "app.exe")
    with safe_open(app, "w") as fp:
        fp.write(
            dedent(
                """\
                import json
                import os
                import sys

                json.dump(
                    {
                        "PYTHONPATH": os.environ.get("PYTHONPATH"),
                        "sys.path": sys.path
                    },
                    sys.stdout
                )
                """
            )
        )

    pex_root = os.path.join(str(tmpdir), "pex_root")

    def create_app_pex(hermetic_scripts):
        # type: (bool) -> str
        pex = os.path.join(
            str(tmpdir), "{}-app.pex".format("hermetic" if hermetic_scripts else "non-hermetic")
        )
        argv = [
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            ot_simulator_src,
            "--exe",
            app,
            "--venv",
            "-o",
            pex,
        ] + boot_args
        if not hermetic_scripts:
            argv.append("--non-hermetic-venv-scripts")
        run_pex_command(argv).assert_success()
        return pex

    cwd = os.path.join(str(tmpdir), "cwd")
    os.mkdir(cwd)

    # A standard hermetic venv pex should be able to see PYTHONPATH but not have its sys.path
    # tainted by it.
    hermetic_app_pex = create_app_pex(hermetic_scripts=True)
    hermetic = json.loads(
        subprocess.check_output(
            args=[hermetic_app_pex], cwd=cwd, env=make_env(PYTHONPATH="ambient")
        )
    )
    assert "ambient" == hermetic["PYTHONPATH"]
    assert os.path.join(cwd, "ambient") not in hermetic["sys.path"]

    # A non-hermetic venv pex should be able to both see PYTHONPATH and have it affect its sys.path.
    non_hermetic_app_pex = create_app_pex(hermetic_scripts=False)
    baseline = json.loads(
        subprocess.check_output(
            args=[non_hermetic_app_pex], cwd=cwd, env=make_env(PYTHONPATH="ambient")
        )
    )
    assert "ambient" == baseline["PYTHONPATH"]
    assert os.path.join(cwd, "ambient") in baseline["sys.path"]

    # A non-hermetic venv pex should have the non-hermeticity extend to its console scripts in
    # addition to the main entry point `pex` script.
    instrumented = json.loads(
        subprocess.check_output(
            args=[non_hermetic_app_pex, non_hermetic_app_pex],
            cwd=cwd,
            env=make_env(PYTHONPATH="ambient", PEX_SCRIPT="instrument"),
        )
    )
    assert "injected:ambient" == instrumented["PYTHONPATH"]
    assert sorted(
        map(os.path.realpath, baseline["sys.path"] + [os.path.join(cwd, "injected")])
    ) == sorted(map(os.path.realpath, instrumented["sys.path"]))
