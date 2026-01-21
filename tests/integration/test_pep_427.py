# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
import os.path
import re
from glob import glob
from textwrap import dedent

import pytest

from pex.common import CopyMode, safe_open
from pex.os import is_exe
from pex.pep_427 import InstallableWheel, InstallPaths, ZipMetadata, install_wheel_interpreter
from pex.pip.installation import get_pip
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from pex.wheel import Wheel
from testing import WheelBuilder, make_env, run_pex_command, subprocess
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Any, List


def test_install_wheel_interpreter(tmpdir):
    # type: (Any) -> None

    venv_dir = os.path.join(str(tmpdir), "venv")
    venv = Virtualenv.create(venv_dir, install_pip=InstallationChoice.YES)
    cowsay_script = venv.bin_path("cowsay")
    assert not os.path.exists(cowsay_script)

    download_dir = os.path.join(str(tmpdir), "downloads")
    get_pip(resolver=ConfiguredResolver.default()).spawn_download_distributions(
        download_dir=download_dir, requirements=["cowsay==5.0"]
    ).wait()

    wheel_dir = os.path.join(str(tmpdir), "wheels")
    get_pip(resolver=ConfiguredResolver.default()).spawn_build_wheels(
        requirements=glob(os.path.join(download_dir, "*.tar.gz")), wheel_dir=wheel_dir
    ).wait()
    wheels = glob(os.path.join(wheel_dir, "*.whl"))
    assert 1 == len(wheels)
    cowsay_wheel = wheels[0]

    install_wheel_interpreter(cowsay_wheel, interpreter=venv.interpreter)
    assert is_exe(cowsay_script)
    assert b"5.0\n" == subprocess.check_output(args=[cowsay_script, "--version"])

    pip = venv.bin_path("pip")
    subprocess.check_call(args=[pip, "uninstall", "--yes", "cowsay"])
    assert not os.path.exists(cowsay_script)


def test_install_scripts(tmpdir):
    # type: (Any) -> None

    # N.B.: This example was taken from https://github.com/pypa/pip/issues/10661.
    top = os.path.join(str(tmpdir), "top")
    with safe_open(os.path.join(top, "mypackage", "__init__.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                def do_some_preprocessing():
                    print('Done some preprocessing')
                    print('Now starting an interactive session')
                """
            )
        )
    with safe_open(os.path.join(top, "scripts", "interactive_script.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                #!python -i

                import mypackage

                mypackage.do_some_preprocessing()
                """
            )
        )
    with safe_open(os.path.join(top, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup

                setup(
                    name='mypackage',
                    version='0.0.1',
                    packages=['mypackage'],
                    scripts=['scripts/interactive_script.py']
                )
                """
            )
        )

    wheels = os.path.join(str(tmpdir), "wheels")
    wheel = WheelBuilder(source_dir=top, wheel_dir=wheels).bdist()

    venv_dir = os.path.join(str(tmpdir), "venv")
    venv = Virtualenv.create(venv_dir)
    script = venv.bin_path("interactive_script.py")
    assert not os.path.exists(script)

    install_wheel_interpreter(wheel, interpreter=venv.interpreter)
    assert is_exe(script)

    process = subprocess.Popen(
        args=[script],
        env=make_env(TERM=os.environ.get("TERM", "xterm")),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
    )
    output, _ = process.communicate()
    assert re.match(
        br"^Done some preprocessing\nNow starting an interactive session\n>>>>?$", output.strip()
    ), output


@pytest.mark.parametrize(
    "pex_venv_args",
    [pytest.param([], id="symlinks"), pytest.param(["--venv-site-packages-copies"], id="copies")],
)
@pytest.mark.parametrize(
    "copy_mode", [pytest.param(copy_mode, id=str(copy_mode)) for copy_mode in CopyMode.values()]
)
def test_install_pex_venv_distributions(
    tmpdir,  # type: Tempdir
    pex_venv_args,  # type: List[str]
    copy_mode,  # type: CopyMode.Value
):
    # type: (...) -> None
    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("cowsay.pex")
    result = run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "cowsay<6",
            "-c",
            "cowsay",
            "-o",
            pex,
            "--seed",
            "verbose",
            "--venv",
        ]
        + pex_venv_args
    )
    result.assert_success()
    src_vnv = Virtualenv(venv_dir=os.path.dirname(json.loads(result.output)["pex"]))

    dst_venv = Virtualenv.create(tmpdir.join("venv"))
    for dist in src_vnv.iter_distributions():
        wheel = Wheel.load(dist.location, project_name=dist.metadata.project_name)
        installable_wheel = InstallableWheel(
            wheel=wheel,
            install_paths=InstallPaths.interpreter(
                interpreter=src_vnv.interpreter,
                project_name=wheel.project_name,
                root_is_purelib=wheel.root_is_purelib,
            ),
            zip_metadata=ZipMetadata.read(wheel),
        )
        install_wheel_interpreter(
            wheel=installable_wheel, interpreter=dst_venv.interpreter, copy_mode=copy_mode
        )

    assert b"| Moo! |" in subprocess.check_output(args=[pex, "Moo!"])
