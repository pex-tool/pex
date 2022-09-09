#!/usr/bin/env python3
# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# N.B.: This script must work with all Pythons we test against including Python 2.7.

from __future__ import print_function

import os
import re


def main():
    # type: () -> None
    print("Test Control Environment Variables:")
    for var, value in sorted(os.environ.items()):
        if re.search(r"(PEX|PYTHON)", var) and var != "PYTHONHASHSEED":
            print("{var}={value}".format(var=var, value=value))


if __name__ == "__main__":
    main()
