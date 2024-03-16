# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pytest

from pex.typing import TYPE_CHECKING
from testing.docker import DockerVirtualenvRunner

if TYPE_CHECKING:
    from typing import Any


@pytest.fixture
def fedora39_virtualenv_runner(tmpdir):
    # type: (Any) -> DockerVirtualenvRunner

    return DockerVirtualenvRunner.create(
        base_image="fedora:39",
        python="python3.12",
        virtualenv_version="20.25.1",
        tmpdir=str(tmpdir),
    )
