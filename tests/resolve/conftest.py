# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from argparse import ArgumentParser

import pytest


@pytest.fixture
def parser():
    # type: () -> ArgumentParser
    return ArgumentParser()
