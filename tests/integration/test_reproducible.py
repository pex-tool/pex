# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import filecmp
import os
import sys
from textwrap import dedent
from zipfile import ZipFile

from pex.common import temporary_dir
from pex.compatibility import PY2
from pex.testing import (
    PY27,
    PY37,
    PY310,
    create_pex_command,
    ensure_python_interpreter,
    run_command_with_jitter,
    run_commands_with_jitter,
    temporary_content,
)
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Optional, List


def assert_reproducible_build(
    args,  # type: List[str]
    pythons=None,  # type: Optional[Iterable[str]]
):
    # type: (...) -> None
    with temporary_dir() as td:

        def explode_pex(path):
            with ZipFile(path) as zf:
                pex_name, _ = os.path.splitext(path)
                destination_dir = os.path.join(td, "pex{}".format(pex_name))
                zf.extractall(path=destination_dir)
                return [os.path.join(destination_dir, member) for member in sorted(zf.namelist())]

        if pythons:
            pexes = run_commands_with_jitter(
                path_argument="--output-file",
                commands=[
                    create_pex_command(
                        args=args + ["--python-shebang", "/usr/bin/env python"],
                        python=python,
                        quiet=True,
                    )
                    for python in pythons
                ],
            )
        else:
            pexes = run_command_with_jitter(
                create_pex_command(args=args, quiet=True), path_argument="--output-file", count=3
            )

        pex_members = {pex: explode_pex(path=pex) for pex in pexes}
        pex1 = pexes.pop()
        for pex2 in pexes:
            # First compare file-by-file for easier debugging.
            for member1, member2 in zip(pex_members[pex1], pex_members[pex2]):
                assert not os.path.isdir(member1) ^ os.path.isdir(member2)
                if os.path.isdir(member1):
                    continue
                # Check that each file has the same content.
                with open(member1, "rb") as f1, open(member2, "rb") as f2:
                    assert list(f1.readlines()) == list(
                        f2.readlines()
                    ), "{} and {} have different content.".format(member1, member2)
                # Check that the entire file is equal, including metadata.
                assert filecmp.cmp(member1, member2, shallow=False)
            # Finally, check that the .pex files are byte-for-byte identical.
            assert filecmp.cmp(pex1, pex2, shallow=False)


MAJOR_COMPATIBLE_PYTHONS = (
    (sys.executable, ensure_python_interpreter(PY27))
    if PY2
    else (sys.executable, ensure_python_interpreter(PY37), ensure_python_interpreter(PY310))
)
MIXED_MAJOR_PYTHONS = (
    sys.executable,
    ensure_python_interpreter(PY27),
    ensure_python_interpreter(PY37),
    ensure_python_interpreter(PY310),
)


def test_reproducible_build_no_args():
    # type: () -> None
    assert_reproducible_build([], pythons=MIXED_MAJOR_PYTHONS)


def test_reproducible_build_bdist_requirements():
    # type: () -> None
    # We test both a pure Python wheel (six) and a platform-specific wheel (cryptography).
    assert_reproducible_build(
        [
            "six==1.12.0",
            "cryptography=={version}".format(version="2.6.1" if PY2 else "3.4.8"),
        ]
    )


def test_reproducible_build_sdist_requirements():
    # type: () -> None
    # The python-crontab sdist will be built as py2-none-any or py3-none-any depending on the
    # Python major version since it is not marked as universal in the sdist.
    assert_reproducible_build(["python-crontab==2.3.6"], pythons=MAJOR_COMPATIBLE_PYTHONS)


def test_reproducible_build_m_flag():
    # type: () -> None
    assert_reproducible_build(["-m", "pydoc"], pythons=MIXED_MAJOR_PYTHONS)


def test_reproducible_build_c_flag_from_source():
    # type: () -> None
    setup_cfg = dedent(
        """\
        [wheel]
        universal = 1
        """
    )
    setup_py = dedent(
        """\
        from setuptools import setup

        setup(
            name='my_app',
            entry_points={'console_scripts': ['my_app_function = my_app:do_something']},
        )
        """
    )
    my_app = dedent(
        """\
        def do_something():
            return "reproducible"
        """
    )
    with temporary_content(
        {"setup.cfg": setup_cfg, "setup.py": setup_py, "my_app.py": my_app}
    ) as project_dir:
        assert_reproducible_build(
            [project_dir, "-c", "my_app_function"], pythons=MIXED_MAJOR_PYTHONS
        )


def test_reproducible_build_c_flag_from_dependency():
    # type: () -> None
    # The futurize script installed depends on the version of python being used; so we don't try
    # to mix Python 2 with Python 3 as in many other reproducibility tests.
    assert_reproducible_build(
        ["future==0.17.1", "-c", "futurize"], pythons=MAJOR_COMPATIBLE_PYTHONS
    )


def test_reproducible_build_python_flag():
    # type: () -> None
    assert_reproducible_build(["--python=python2.7"], pythons=MIXED_MAJOR_PYTHONS)


def test_reproducible_build_python_shebang_flag():
    # type: () -> None
    # Passing `python_versions` override `--python-shebang`; so we don't do that here.
    assert_reproducible_build(["--python-shebang=/usr/bin/python"])
