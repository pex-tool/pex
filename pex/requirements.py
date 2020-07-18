# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import re


class UnsupportedLine(Exception):
    pass


def _get_parameter(line):
    sline = line.split("=")
    if len(sline) != 2:
        sline = line.split()
    if len(sline) != 2:
        raise UnsupportedLine("Unrecognized line format: %s" % line)
    return sline[1]


def local_project_from_requirement(requirement, relpath=None):
    """Return the absolute path for a local project requirement.

    :param str requirement: The requirement string to parse.
    :param str relpath: The base path to measure the local project path from.
    :return: The absolute path of the local project requirement or `None` if the requirement string
             does not represent a local project requirement.
    """

    relpath = relpath or os.getcwd()

    # Strip any extras that may be present. e.g. given: `./local/setup-py-project[foo]`
    # produce: `./local/setup-py-project`
    maybe_dir = re.sub(r"\[(?#extras).*\]$", "", requirement)
    maybe_abs_dir = maybe_dir if os.path.isabs(maybe_dir) else os.path.join(relpath, maybe_dir)
    if any(os.path.isfile(os.path.join(maybe_abs_dir, f)) for f in ("setup.py", "pyproject.toml")):
        return maybe_abs_dir


# Process lines in the requirements.txt format as defined here:
# https://pip.pypa.io/en/latest/reference/pip_install.html#requirements-file-format
# Note that we're only interested in requirement specifiers that look like local directories and not
# any pip options which we'll let pip handle.
def _iter_local_projects(lines, relpath=None):
    relpath = relpath or os.getcwd()

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        elif line.startswith(("-r ", "--requirement")):
            path = os.path.join(relpath, _get_parameter(line))
            for local_project in local_projects_from_requirement_file(path):
                yield local_project
        elif not line.startswith("-"):
            local_project = local_project_from_requirement(line, relpath=relpath)
            if local_project:
                yield local_project


def local_projects_from_requirement_file(filename):
    """Return a list of local project absolute paths from a requirements.txt file.

    :param filename: The filename of the requirements file.
    """

    relpath = os.path.dirname(filename)
    with open(filename, "r") as fp:
        return _iter_local_projects(fp.readlines(), relpath=relpath)
