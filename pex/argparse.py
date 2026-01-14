# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import shlex
from argparse import Action, ArgumentError

from pex.os import WINDOWS


class HandleBoolAction(Action):
    """An action for bool options that parses `--no-foo` or `--not-foo` as `--foo=False`"""

    def __init__(self, *args, **kwargs):
        kwargs["nargs"] = 0
        super(HandleBoolAction, self).__init__(*args, **kwargs)

    def __call__(self, parser, namespace, value, option_str=None):
        setattr(namespace, self.dest, not option_str.startswith("--no"))


class InjectEnvAction(Action):
    def __call__(self, parser, namespace, value, option_str=None):
        components = value.split("=", 1)
        if len(components) != 2:
            raise ArgumentError(
                self,
                "Environment variable values must be of the form `name=value`. "
                "Given: {value}".format(value=value),
            )
        self.default.append(tuple(components))


class InjectArgAction(Action):
    def __call__(self, parser, namespace, value, option_str=None):
        self.default.extend(shlex.split(value, posix=not WINDOWS))
