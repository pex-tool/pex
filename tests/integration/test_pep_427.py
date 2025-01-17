# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import re
import subprocess
from glob import glob
from textwrap import dedent

from pex.common import safe_open
from pex.executables import is_exe
from pex.pep_427 import install_wheel_interpreter
from pex.pip.installation import get_pip
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing import WheelBuilder, make_env

if TYPE_CHECKING:
    from typing import Any


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
        distributions=glob(os.path.join(download_dir, "*.tar.gz")), wheel_dir=wheel_dir
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
