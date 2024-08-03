# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).


class Globals(dict):
    """The globals dict returned by PEX executions that evaluate code without exiting / exec'ing."""

    def __int__(self):
        # type: () -> int

        # When a globals dict is returned, this should always be interpreted as a successful exit.
        return 0
