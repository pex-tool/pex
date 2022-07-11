# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import re

import pytest

from pex.pep_425 import CompatibilityTags
from pex.third_party.packaging import tags
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Iterable


def equatable(tags):
    # type: (Iterable[tags.Tag]) -> Any
    return sorted(map(str, tags))


def test_tags_from_wheel_nominal():
    # type: () -> None

    assert equatable(tags.parse_tag("py2.py3-none-any")) == equatable(
        CompatibilityTags.from_wheel("foo-1.2.3-py2.py3-none-any.whl")
    )
    assert equatable(CompatibilityTags.from_strings(["py2-none-any", "py3-none-any"])) == equatable(
        CompatibilityTags.from_wheel("foo-1.2.3-py2.py3-none-any.whl")
    )
    assert equatable(tags.parse_tag("py2.py3-none-any")) == equatable(
        CompatibilityTags.from_wheel("foo-1.2.3-build_tag-py2.py3-none-any.whl")
    )
    assert equatable(tags.parse_tag("py3-none-any")) == equatable(
        CompatibilityTags.from_wheel("path/to/bar-4.5.6-py3-none-any.whl")
    )


def test_tags_from_wheel_invalid():
    # type: () -> None

    with pytest.raises(
        ValueError,
        match=re.escape(
            "Can only calculate wheel tags from a filename that ends in .whl per "
            "https://peps.python.org/pep-0427/#file-name-convention, given: "
            "'foo-1.2.3-py2.py3-none-any'"
        ),
    ):
        CompatibilityTags.from_wheel("foo-1.2.3-py2.py3-none-any")

    with pytest.raises(
        ValueError,
        match=re.escape(
            "Can only calculate wheel tags from a filename that ends in "
            "`-{python tag}-{abi tag}-{platform tag}.whl` per "
            "https://peps.python.org/pep-0427/#file-name-convention, given: 'py2.py3-none-any.whl'"
        ),
    ):
        CompatibilityTags.from_wheel("py2.py3-none-any.whl")
