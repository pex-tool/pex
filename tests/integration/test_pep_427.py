# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
from glob import glob

from pex.common import is_exe
from pex.pep_427 import install_wheel_interpreter
from pex.pip.installation import get_pip
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    from typing import Any


def test_install_wheel_interpreter(tmpdir):
    # type: (Any) -> None

    venv_dir = os.path.join(str(tmpdir), "venv")
    venv = Virtualenv.create(venv_dir)
    cowsay_script = venv.bin_path("cowsay")
    assert not os.path.exists(cowsay_script)

    download_dir = os.path.join(str(tmpdir), "downloads")
    get_pip().spawn_download_distributions(
        download_dir=download_dir, requirements=["cowsay==5.0"]
    ).wait()

    wheel_dir = os.path.join(str(tmpdir), "wheels")
    get_pip().spawn_build_wheels(
        distributions=glob(os.path.join(download_dir, "*.tar.gz")), wheel_dir=wheel_dir
    ).wait()
    wheels = glob(os.path.join(wheel_dir, "*.whl"))
    assert 1 == len(wheels)
    cowsay_wheel = wheels[0]

    install_wheel_interpreter(cowsay_wheel, interpreter=venv.interpreter)
    assert is_exe(cowsay_script)
    assert b"5.0\n" == subprocess.check_output(args=[cowsay_script, "--version"])

    pip = venv.install_pip()
    subprocess.check_call(args=[pip, "uninstall", "--yes", "cowsay"])
    assert not os.path.exists(cowsay_script)
