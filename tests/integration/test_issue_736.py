# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess

from pex.common import safe_copy, temporary_dir
from pex.testing import built_wheel, make_env, make_source_dir, run_pex_command


def test_requirement_setup_py_with_extras():
    # type: () -> None
    with make_source_dir(
        name="project1", version="1.0.0", extras_require={"foo": ["project2"]}
    ) as project1_dir:
        with built_wheel(name="project2", version="2.0.0") as project2_bdist:
            with temporary_dir() as td:
                safe_copy(project2_bdist, os.path.join(td, os.path.basename(project2_bdist)))

                project1_pex = os.path.join(td, "project1.pex")
                result = run_pex_command(
                    ["-f", td, "-o", project1_pex, "{}[foo]".format(project1_dir)]
                )
                result.assert_success()

                output = subprocess.check_output(
                    [
                        project1_pex,
                        "-c",
                        "from project2 import my_module; my_module.do_something()",
                    ],
                    env=make_env(PEX_INTERPRETER="1"),
                )
                assert output.decode("utf-8").strip() == u"hello world!"
