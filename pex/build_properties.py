# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import logging
import os.path
import subprocess
from argparse import ArgumentTypeError, Namespace, _ActionsContainer

from pex.argparse import HandleBoolAction
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)


def register_options(parser):
    # type: (_ActionsContainer) -> None

    parser.add_argument(
        "--build-properties",
        dest="build_properties",
        help=(
            "Use the given JSON for PEX-INFO build_properties. The JSON value can be an object "
            "literal or the path to a file containing a JSON object literal."
        ),
    )
    parser.add_argument(
        "--build-property",
        dest="build_properties_entries",
        default=[],
        action="append",
        help=(
            "Add a build property entry. Entries are specified in the form `<name>=<value>` and "
            "values can either be JSON values or strings. For example `--build-property foo=bar` "
            'adds the property `"foo": "bar"` to the build properties object and '
            '`--build-property \'foo=["spam", 42]\'` adds the property `"foo": ["spam", 42]`.'
        ),
    )
    parser.add_argument(
        "--record-git-state",
        "--no-record-git-state",
        dest="record_git_state",
        default=False,
        action=HandleBoolAction,
        help=(
            "Records the current git state in build properties in a `git_state` object containing "
            "entries for the `commit`, the commit `description`, the `branch` if on a branch and "
            "the `tag` if currently checked out to an exact tag."
        ),
    )


def _capture_git_state():
    # type: () -> Mapping[str, Any]

    git_state = {}  # type: Dict[str, Any]

    def run_git_cmd(*git_cmd):
        # type: (...) -> Tuple[List[str], subprocess.Popen]

        args = ["git"] + list(git_cmd)
        return args, subprocess.Popen(args=args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def add_git_state(
        key,  # type: str
        git_cmd,  # type: List[str]
        git_process,  # type: subprocess.Popen
        default=None,  # type: Optional[str]
    ):
        # type: (...) -> None

        stdout, stderr = git_process.communicate()
        if git_process.returncode == 0:
            git_state[key] = stdout.decode("utf-8").strip()
            return
        if default is not None:
            git_state[key] = default
            return
        logger.warning("Failed to gather {key!r} git state for build properties.".format(key=key))
        logger.info(
            "Got exit code {exit_code} for command: {git_cmd}".format(
                exit_code=git_process.returncode, git_cmd=git_cmd
            )
        )
        logger.debug("Got STDERR:\n{stderr}".format(stderr=stderr.decode("utf-8")))

    desc_args, desc_process = run_git_cmd("describe", "--always", "--dirty", "--long")
    commit_args, commit_process = run_git_cmd("rev-parse", "HEAD")
    branch_args, branch_process = run_git_cmd("branch", "--show-current")
    tag_args, tag_process = run_git_cmd("describe", "--exact-match")
    add_git_state("description", desc_args, desc_process)
    add_git_state("commit", commit_args, commit_process)
    add_git_state("branch", branch_args, branch_process, default="")
    add_git_state("tag", tag_args, tag_process, default="")

    return git_state


class BuildProperties(dict):
    @classmethod
    def from_options(cls, options):
        # type: (Namespace) -> BuildProperties

        build_properties = cls()

        if options.build_properties:
            if os.path.isfile(options.build_properties):
                try:
                    with open(options.build_properties) as fp:
                        properties = json.load(fp)
                except (OSError, ValueError) as e:
                    raise ArgumentTypeError(
                        "Failed to load build properties data from {path}: {err}".format(
                            path=options.build_properties, err=e
                        )
                    )
            else:
                try:
                    properties = json.loads(options.build_properties)
                except ValueError as e:
                    raise ArgumentTypeError(
                        "Failed to load build properties data from json string: {err}".format(err=e)
                    )
            build_properties.update(properties)

        for prop in options.build_properties_entries:
            name, sep, value = prop.partition("=")
            if not sep:
                raise ArgumentTypeError(
                    "Invalid --build-property value {value}. Values must be in `<name>=<value>` "
                    "form".format(value=prop)
                )

            try:
                build_properties[name] = json.loads(value)
            except ValueError:
                build_properties[name] = value

        if options.record_git_state:
            build_properties["git_state"] = _capture_git_state()

        return build_properties
