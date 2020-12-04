# coding=utf-8
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import email

from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.pkg_resources import DistInfoDistribution, Distribution, Requirement
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, Iterator, Optional


_PKG_INFO_BY_DIST = {}  # type: Dict[Distribution, Optional[email.message.Message]]


def _parse_pkg_info(dist):
    # type: (Distribution) -> Optional[email.message.Message]
    if dist not in _PKG_INFO_BY_DIST:
        if not dist.has_metadata(DistInfoDistribution.PKG_INFO):
            pkg_info = None
        else:
            metadata = dist.get_metadata(DistInfoDistribution.PKG_INFO)
            pkg_info = email.parser.Parser().parsestr(metadata)
        _PKG_INFO_BY_DIST[dist] = pkg_info
    return _PKG_INFO_BY_DIST[dist]


def requires_python(dist):
    # type: (Distribution) -> Optional[SpecifierSet]
    """Examines dist for `Python-Requires` metadata and returns version constraints if any.

    See: https://www.python.org/dev/peps/pep-0345/#requires-python

    :param dist: A distribution to check for `Python-Requires` metadata.
    :return: The required python version specifiers.
    """
    pkg_info = _parse_pkg_info(dist)
    if pkg_info is None:
        return None

    python_requirement = pkg_info.get("Requires-Python", None)
    if python_requirement is None:
        return None
    return SpecifierSet(python_requirement)


def requires_dists(
    dist,  # type: Distribution
    include_1_1_requires=True,  # type: bool
):
    # type: (...) -> Iterator[Requirement]
    """Examines dist for and returns any declared requirements.

    Looks for `Requires-Dist` metadata and, optionally, the older `Requires` metadata if
    `include_1_1_requires`.

    See:
    + https://www.python.org/dev/peps/pep-0345/#requires-dist-multiple-use
    + https://www.python.org/dev/peps/pep-0314/#requires-multiple-use

    :param dist: A distribution to check for requirement metadata.
    :return: All requirements found.
    """
    pkg_info = _parse_pkg_info(dist)
    if pkg_info is None:
        return

    for requires_dist in pkg_info.get_all("Requires-Dist", ()):
        yield Requirement.parse(requires_dist)

    if include_1_1_requires:
        for requires in pkg_info.get_all("Requires", ()):
            yield Requirement.parse(requires)
