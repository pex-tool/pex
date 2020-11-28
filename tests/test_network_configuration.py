# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pytest

from pex.network_configuration import NetworkConfiguration


def test_headers_as_dict():
    # type: () -> None
    assert {} == NetworkConfiguration.create().headers_as_dict()
    assert {} == NetworkConfiguration.create(headers=[]).headers_as_dict()
    assert {"A_NAME": "B_VALUE", "C_NAME": "D_VALUE"} == NetworkConfiguration.create(
        headers=["A_NAME:B_VALUE", "C_NAME:D_VALUE"]
    ).headers_as_dict()


def test_headers_bad():
    # type: () -> None
    with pytest.raises(AssertionError) as exec_info:
        NetworkConfiguration.create(headers=["A_NAME:B_VALUE", "C_BAD", "D_NAME:E_VALUE", "F_BAD"])

    message_lines = frozenset(str(exec_info.value).splitlines())
    assert "C_BAD" in message_lines
    assert "F_BAD" in message_lines
    assert 4 == len(message_lines)
