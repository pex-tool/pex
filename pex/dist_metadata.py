# coding=utf-8
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import email

from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.pkg_resources import DistInfoDistribution, Distribution
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional


def requires_python(dist):
    # type: (Distribution) -> Optional[SpecifierSet]
    """Examines dist for `Python-Requires` metadata and returns version constraints if any.

    See: https://www.python.org/dev/peps/pep-0345/#requires-python

    :param dist: A distribution to check for `Python-Requires` metadata.
    :return: The required python version specifiers.
    """
    if not dist.has_metadata(DistInfoDistribution.PKG_INFO):
        return None

    metadata = dist.get_metadata(DistInfoDistribution.PKG_INFO)
    pkg_info = email.parser.Parser().parsestr(metadata)
    python_requirement = pkg_info.get("Requires-Python")
    if not python_requirement:
        return None
    return SpecifierSet(python_requirement)
