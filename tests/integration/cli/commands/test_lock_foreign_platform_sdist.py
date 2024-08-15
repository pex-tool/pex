# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess
from textwrap import dedent

import pytest

from pex import targets
from pex.build_system import pep_517
from pex.common import safe_open
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.result import try_
from pex.typing import TYPE_CHECKING
from testing import PY_VER, data, run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    PY_VER < (3, 7), reason="The meson build system used in this test requires `Python>=3.7`."
)
def test_lock_foreign_platform_sdist(tmpdir):
    # type: (Any) -> None

    # When locking a requirement that only has an sdist available we need to build a wheel if the
    # build backend does not support the PEP-517 `prepare_metadata_for_build_wheel` hook (
    # https://peps.python.org/pep-0517/#prepare-metadata-for-build-wheel). The meson-python 0.16.0
    # build backend does not support `prepare_metadata_for_build_wheel`; so we use it here to prove
    # we can lock for foreign platforms when neither a wheel nor a build backend supporting
    # `prepare_metadata_for_build_wheel` is available. The assumption is the same as for a
    # `--style universal` lock: the metadata for a given project version is consistent across its
    # distributions. We know the assumption is sometimes violated in the wild, but we embrace it
    # here again as the only sane option.

    project_dir = os.path.join(str(tmpdir), "project")
    with safe_open(os.path.join(project_dir, "module.c"), "w") as fp:
        fp.write(
            dedent(
                """\
                #include <Python.h>

                static PyObject* foo(PyObject* self)
                {
                    return PyUnicode_FromString("bar");
                }

                static PyMethodDef methods[] = {
                    {"foo", (PyCFunction)foo, METH_NOARGS, NULL},
                    {NULL, NULL, 0, NULL},
                };

                static struct PyModuleDef module = {
                    PyModuleDef_HEAD_INIT,
                    "module",
                    NULL,
                    -1,
                    methods,
                };

                PyMODINIT_FUNC PyInit_module(void)
                {
                    return PyModule_Create(&module);
                }
                """
            )
        )
    with safe_open(os.path.join(project_dir, "meson.build"), "w") as fp:
        fp.write(
            dedent(
                """\
                project('purelib-and-platlib', 'c')

                py = import('python').find_installation(pure: false)

                py.extension_module(
                    'module',
                    'module.c',
                    install: true,
                )
                """
            )
        )
    with safe_open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                build-backend = "mesonpy"
                requires = ["meson-python==0.16.0"]

                [project]
                name = "module"
                version = "0.0.1"
                requires-python = ">=3.7"
                """
            )
        )

    # N.B.: Meson requires a VCS enclosing the project.
    subprocess.check_call(["git", "init", project_dir])
    subprocess.check_call(["git", "config", "user.email", "you@example.com"], cwd=project_dir)
    subprocess.check_call(["git", "config", "user.name", "Your Name"], cwd=project_dir)
    subprocess.check_call(["git", "add", "."], cwd=project_dir)
    subprocess.check_call(
        ["git", "commit", "--no-gpg-sign", "-m", "Initial Commit."], cwd=project_dir
    )

    find_links = os.path.join(str(tmpdir), "find_links")
    current_target = targets.current()
    try_(
        pep_517.build_sdist(
            project_directory=project_dir,
            dist_dir=find_links,
            target=current_target,
            resolver=ConfiguredResolver.default(),
        )
    )

    complete_platform = data.path("platforms", "complete_platform_linux_armv7l_py312.json")
    lock = os.path.join(str(tmpdir), "lock.json")
    find_links_args = [
        "--find-links",
        find_links,
        "--path-mapping",
        "FIND_LINKS|{find_links}".format(find_links=find_links),
    ]
    run_pex3(
        "lock",
        "create",
        "module==0.0.1",
        "--only-build",
        "module",
        "--complete-platform",
        complete_platform,
        "--indent",
        "2",
        "-o",
        lock,
        *find_links_args
    ).assert_success()

    # Even though the lock is for a foreign platform, it should be compatible with the local
    # platform since the C extension is pure-python C.
    run_pex_command(
        args=find_links_args + ["--lock", lock, "--", "-c", "import module; print(module.foo())"]
    ).assert_success(expected_output_re=r"^bar$")
