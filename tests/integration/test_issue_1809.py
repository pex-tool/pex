# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import shutil
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.typing import TYPE_CHECKING
from testing import PY310, ensure_python_distribution, run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    sys.version_info >= (3, 12),
    reason="The test requires using pex 2.1.92 which only supports up to Python 3.11",
)
def test_excepthook_scrubbing(tmpdir):
    # type: (Any) -> None

    original_python_installation, original_python, _, _ = ensure_python_distribution(PY310)

    custom_python_installation = os.path.join(str(tmpdir), "custom")
    shutil.copytree(original_python_installation, custom_python_installation)
    custom_python = os.path.join(custom_python_installation, "bin", "python")

    project_dir = os.path.join(str(tmpdir), "custom_excepthook")
    with safe_open(os.path.join(project_dir, "custom_excepthook.py"), "w") as fp:
        fp.write("def custom_excepthook(typ, val, _tb): print('EXC: {} {}'.format(typ, val))")
    with safe_open(os.path.join(project_dir, "custom_excepthook.pth"), "w") as fp:
        fp.write("import custom_excepthook; sys.excepthook = custom_excepthook.custom_excepthook")

    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from distutils import sysconfig

                from setuptools import setup


                setup(
                    name="custom_excepthook",
                    version="0.0.1",
                    py_modules=["custom_excepthook"],
                    data_files=[(sysconfig.get_python_lib(), ["custom_excepthook.pth"])]
                )
                """
            )
        )

    subprocess.check_call(args=[custom_python, "-m", "pip", "install", project_dir])

    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "app.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import sys


                if getattr(sys.excepthook, "__name__", None) == "custom_excepthook":
                    import custom_excepthook

                print("SUCCESS")
                """
            )
        )

    pex = os.path.join(str(tmpdir), "pex")
    create_pex_args = ["-D", src, "-m", "app", "-o", pex]

    # Ensure this complicated test setup reproduces the original error in
    # https://github.com/pex-tool/pex/issues/1809
    # (via https://github.com/pantsbuild/pants/issues/15877).
    run_pex_command(args=["pex==2.1.92", "-c", "pex", "--"] + create_pex_args).assert_success()

    # A Python installation without the custom excepthook installed via .pth should work just fine.
    assert "SUCCESS\n" == subprocess.check_output(args=[original_python, pex]).decode("utf-8")

    # But with the custom excepthook installed pre-PEX boot, we should reproduce earlier failures.
    process = subprocess.Popen(args=[custom_python, pex], stdout=subprocess.PIPE)
    stdout, _ = process.communicate()
    assert 0 != process.returncode
    assert (
        "EXC: <class 'ModuleNotFoundError'> No module named 'custom_excepthook'\n"
        == stdout.decode("utf-8")
    )

    # Now demonstrate the fix.
    run_pex_command(args=create_pex_args).assert_success()
    assert "SUCCESS\n" == subprocess.check_output(args=[custom_python, pex]).decode("utf-8")
