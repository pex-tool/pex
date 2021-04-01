# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.third_party.packaging.utils import canonicalize_name
from pex.third_party.pkg_resources import Distribution, Requirement
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import Union
else:
    from pex.third_party import attr


def _canonicalize_project_name(project_nameable):
    # type: (Union[Distribution, Requirement, str]) -> str
    project_name = (
        project_nameable.project_name
        if isinstance(project_nameable, (Distribution, Requirement))
        else project_nameable
    )
    return cast(str, canonicalize_name(project_name))


@attr.s(frozen=True)
class ProjectName(object):
    """Encodes a canonicalized project name as per PEP-503.

    See: https://www.python.org/dev/peps/pep-0503/#normalized-names
    """

    project_name = attr.ib(converter=_canonicalize_project_name)  # type: str

    def __str__(self):
        # type: () -> str
        return self.project_name


def distribution_satisfies_requirement(
    distribution,  # type: Distribution
    requirement,  # type: Requirement
):
    # type: (...) -> bool
    """Determines if the given distribution satisfies the given requirement.

    N.B.: Any environment markers present in the requirement are not evaluated. The requirement is
    considered satisfied if project names match and the distribution version is in the requirement's
    specified range, if any.
    """
    # N.B.: Although Requirement.__contains__ handles Distributions directly, it compares the
    # Distribution key with the Requirement key and these keys are not properly canonicalized
    # per PEP-503; so we compare project names here on our own.
    if ProjectName(distribution) != ProjectName(requirement):
        return False
    return distribution.version in requirement
