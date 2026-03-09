# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
from textwrap import dedent

from pex.common import safe_open


class LocalProject(str):
    def edit_all_caps(self, all_caps):
        # type: (bool) -> None
        with open(os.path.join(self, "local_project.py"), "a") as fp:
            print("ALL_CAPS={all_caps!r}".format(all_caps=all_caps), file=fp)


def create(project_dir):
    # type: (str) -> LocalProject
    with safe_open(os.path.join(project_dir, "local_project.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from __future__ import print_function

                import sys


                ALL_CAPS = False


                def main():
                    text = sys.argv[1:]
                    if ALL_CAPS:
                        text[:] = [item.upper() for item in text]
                    print(*text, end="")

                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = local_project
                version = 0.0.1

                [options]
                py_modules =
                    local_project

                [options.entry_points]
                console_scripts =
                    local-project = local_project:main
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write("from setuptools import setup; setup()")
    with open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools"]
                build-backend = "setuptools.build_meta"
                """
            )
        )
    return LocalProject(project_dir)
