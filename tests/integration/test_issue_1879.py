# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path

import pytest

from pex.layout import Layout
from pex.pep_427 import InstallableType
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.pep_427 import get_installable_type_flag

if TYPE_CHECKING:
    from typing import Any


# N.B.: The ordering of decorators is just so to get the test ids to match with what the test does
# for sanity's sake.
#
# So, we get "test_overwrite[zipapp-loose]" which indicates a test of the transition from
# zipapp (layout1) to loose (layout2) and "test_overwrite[packed-packed]" to indicate an overwrite
# of the packed layout by another packed layout, etc.
@pytest.mark.parametrize(
    "installable_type2",
    [
        pytest.param(installable_type, id=installable_type.value)
        for installable_type in InstallableType.values()
    ],
)
@pytest.mark.parametrize(
    "layout2", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
@pytest.mark.parametrize(
    "installable_type1",
    [
        pytest.param(installable_type, id=installable_type.value)
        for installable_type in InstallableType.values()
    ],
)
@pytest.mark.parametrize(
    "layout1", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
def test_overwrite(
    tmpdir,  # type: Any
    layout1,  # type: Layout.Value
    installable_type1,  # type: InstallableType.Value
    layout2,  # type: Layout.Value
    installable_type2,  # type: InstallableType.Value
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")

    run_pex_command(
        args=[
            "-e",
            "one",
            "-o",
            pex,
            "--layout",
            layout1.value,
            get_installable_type_flag(installable_type1),
        ]
    ).assert_success()
    assert layout1 is Layout.identify(pex)
    assert "one" == PexInfo.from_pex(pex).entry_point

    run_pex_command(
        args=[
            "-e",
            "two",
            "-o",
            pex,
            "--layout",
            layout2.value,
            get_installable_type_flag(installable_type2),
        ]
    ).assert_success()
    assert layout2 is Layout.identify(pex)
    assert "two" == PexInfo.from_pex(pex).entry_point
