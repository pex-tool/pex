# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from argparse import Action


class HandleBoolAction(Action):
    """An action for bool options that parses `--no-foo` or `--not-foo` as `--foo=False`"""

    def __init__(self, *args, **kwargs):
        kwargs["nargs"] = 0
        super(HandleBoolAction, self).__init__(*args, **kwargs)

    def __call__(self, parser, namespace, value, option_str=None):
        setattr(namespace, self.dest, not option_str.startswith("--no"))
