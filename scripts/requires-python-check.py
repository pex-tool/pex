#!/usr/bin/env python3

import sys
from textwrap import dedent
from typing import Any

from pex import toml
from pex.compatibility import ConfigParser


def main() -> Any:
    config_parser = ConfigParser()
    config_parser.read("setup.cfg")
    setup_cfg_python_requires = config_parser.get("options", "python_requires")

    pyproject_data = toml.load("pyproject.toml")
    pyproject_requires_python = pyproject_data["project"]["requires-python"]

    if setup_cfg_python_requires != pyproject_requires_python:
        return dedent(
            """\
            The project Requires-Python metadata is inconsistent. Please align the following values:

            setup.cfg:
            [options]
            python_requires = {setup_cfg_python_requires}

            pyproject.toml:
            [project]
            requires-python = "{pyproject_requires_python}"
            """.format(
                setup_cfg_python_requires=setup_cfg_python_requires,
                pyproject_requires_python=pyproject_requires_python,
            )
        )


if __name__ == "__main__":
    sys.exit(main())
