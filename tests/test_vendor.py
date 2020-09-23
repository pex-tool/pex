# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pex.vendor import VendorSpec


def test_pinned():
    # type: () -> None
    vendor_spec = VendorSpec.pinned("foo", "1.2.3")
    assert "foo" == vendor_spec.key
    assert "foo==1.2.3" == vendor_spec.requirement


def test_vcs_valid():
    # type: () -> None
    vendor_spec = VendorSpec.vcs("git+https://github.com/foo.git@da39a3ee#egg=bar")
    assert "bar" == vendor_spec.key
    assert "git+https://github.com/foo.git@da39a3ee#egg=bar" == vendor_spec.requirement


def test_vcs_invalid_no_egg():
    # type: () -> None
    with pytest.raises(ValueError):
        VendorSpec.vcs("git+https://github.com/foo.git@da39a3ee")


def test_vcs_invalid_multiple_egg():
    # type: () -> None
    with pytest.raises(ValueError):
        VendorSpec.vcs("git+https://github.com/foo.git@da39a3ee#egg=bar&egg=foo")
