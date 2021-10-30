# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pytest

from pex import testing


@pytest.fixture(scope="session")
def pex_project_dir():
    # type: () -> str
    return testing.pex_project_dir()
