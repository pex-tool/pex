# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import subprocess
from textwrap import dedent

from pex.common import safe_open
from pex.testing import IS_PYPY2, make_env, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_execute_module_alter_sys(tmpdir):
    # type: (Any) -> None
    src_dir = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src_dir, "issues_1018.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import pickle

                def add(a, b):
                    return a + b

                def main():
                    pickle_add = pickle.dumps(add)
                    add_clone = pickle.loads(pickle_add)
                    print(add_clone(1, 2))

                if __name__ == "__main__":
                    main()
                """
            )
        )
    expected_output = b"3\n"

    # There are 9 ways we can invoke the module above using Pex corresponding to the 2D matrix with
    # axes: {zipapp, unzip, venv} x {entrypoint-function, entrypoint-module, ad-hoc (-m) module}.
    # Of these, zipapp + entrypoint-module is the only combination where we can't both satisfy being
    # able to re-exec a PEX based on argv[0] and support pickling.

    unzip_env = make_env(PEX_UNZIP=1)

    with_ep_pex = os.path.join(str(tmpdir), "test_with_ep.pex")
    run_pex_command(
        args=["-D", src_dir, "-e", "issues_1018:main", "-o", with_ep_pex]
    ).assert_success()
    assert expected_output == subprocess.check_output(args=[with_ep_pex], env=unzip_env)
    assert expected_output == subprocess.check_output(args=[with_ep_pex])

    no_ep_pex = os.path.join(str(tmpdir), "test_no_ep.pex")
    run_pex_command(args=["-D", src_dir, "-o", no_ep_pex]).assert_success()
    assert expected_output == subprocess.check_output(
        args=[no_ep_pex, "-m", "issues_1018"], env=unzip_env
    )
    assert expected_output == subprocess.check_output(args=[no_ep_pex, "-m", "issues_1018"])

    with_module_pex = os.path.join(str(tmpdir), "test_with_module.pex")
    run_pex_command(
        args=["-D", src_dir, "-m", "issues_1018", "-o", with_module_pex]
    ).assert_success()
    assert expected_output == subprocess.check_output(args=[with_module_pex], env=unzip_env)

    # For the case of a PEX zip with a module entrypoint we cannot both get pickling working and
    # support re-execution of the PEX file using sys.argv[0]. Prospective picklers need to either
    # use a function entrypoint as in with_ep_pex or else re-structure their pickling to happen
    # anywhere but in a __name__ == '__main__' module.
    process = subprocess.Popen(args=[with_module_pex], stderr=subprocess.PIPE)
    _, stderr = process.communicate()
    assert process.returncode != 0
    traceback_root = stderr.decode("utf-8").splitlines()[-1]
    if IS_PYPY2:
        assert "TypeError: can't pickle zipimporter objects" == traceback_root, traceback_root
    else:
        assert re.search(r"\bPicklingError\b", traceback_root) is not None, traceback_root
        assert re.search(r"\b__main__\b", traceback_root) is not None
        assert re.search(r"\badd\b", traceback_root) is not None
        assert (
            re.search(r"<function add at 0x[a-f0-9]+>", traceback_root) is not None
        ), traceback_root

    with_ep_venv_pex = os.path.join(str(tmpdir), "test_with_ep_venv.pex")
    run_pex_command(
        args=["-D", src_dir, "-e", "issues_1018:main", "-o", with_ep_venv_pex, "--venv"]
    ).assert_success()
    assert expected_output == subprocess.check_output(args=[with_ep_venv_pex])

    no_ep_venv_pex = os.path.join(str(tmpdir), "test_no_ep_venv.pex")
    result = run_pex_command(args=["-D", src_dir, "-o", no_ep_venv_pex, "--venv", "--seed"])
    result.assert_success()
    no_ep_venv_pex_bin = result.output.strip()
    assert expected_output == subprocess.check_output(
        args=[no_ep_venv_pex_bin, "-m", "issues_1018"]
    )

    with_module_venv_pex = os.path.join(str(tmpdir), "test_with_module_venv.pex")
    run_pex_command(
        args=["-D", src_dir, "-m", "issues_1018", "-o", with_module_venv_pex, "--venv"]
    ).assert_success()
    assert expected_output == subprocess.check_output(args=[with_module_venv_pex])
