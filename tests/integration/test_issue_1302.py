# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import subprocess

from pex.testing import built_wheel, make_env, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_pex_repository_pep503(tmpdir):
    # type: (Any) -> None
    repository_pex = os.path.join(str(tmpdir), "repository.pex")
    with built_wheel(name="foo_bar", version="1.0.0") as wheel_path:
        run_pex_command(
            args=[
                "--no-pypi",
                "--find-links",
                os.path.dirname(wheel_path),
                "Foo._-BAR==1.0.0",
                "-o",
                repository_pex,
                "--include-tools",
            ]
        ).assert_success()

    repository_info = subprocess.check_output(
        args=[repository_pex, "info"], env=make_env(PEX_TOOLS=1)
    )
    assert ["Foo._-BAR==1.0.0"] == json.loads(repository_info.decode("utf-8"))["requirements"]

    foo_bar_pex = os.path.join(str(tmpdir), "foo-bar.pex")
    run_pex_command(
        args=[
            "--pex-repository",
            repository_pex,
            "Foo._-BAR==1.0.0",
            "-o",
            foo_bar_pex,
            "--include-tools",
        ]
    ).assert_success()

    foo_bar_info = subprocess.check_output(args=[foo_bar_pex, "info"], env=make_env(PEX_TOOLS=1))
    assert ["Foo._-BAR==1.0.0"] == json.loads(foo_bar_info.decode("utf-8"))["requirements"]

    subprocess.check_call(args=[foo_bar_pex, "-c", "import foo_bar"])
