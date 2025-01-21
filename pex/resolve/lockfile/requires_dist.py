# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import operator
from collections import defaultdict, deque

from pex.dist_metadata import Requirement
from pex.exceptions import production_assert
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import LockedRequirement, LockedResolve
from pex.sorted_tuple import SortedTuple
from pex.third_party.packaging.markers import Marker, Variable
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Callable, DefaultDict, Dict, Iterable, Iterator, List, Optional, Tuple, Union

    import attr  # vendor:skip

    EvalExtra = Callable[[ProjectName], bool]
else:
    from pex.third_party import attr


_OPERATORS = {
    "in": lambda lhs, rhs: lhs in rhs,
    "not in": lambda lhs, rhs: lhs not in rhs,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    ">": operator.gt,
}


class _Op(object):
    def __init__(self, lhs):
        self.lhs = lhs  # type: EvalExtra
        self.rhs = None  # type: Optional[EvalExtra]


class _And(_Op):
    def __call__(self, extra):
        # type: (ProjectName) -> bool
        production_assert(self.rhs is not None)
        return self.lhs(extra) and cast("EvalExtra", self.rhs)(extra)


class _Or(_Op):
    def __call__(self, extra):
        # type: (ProjectName) -> bool
        production_assert(self.rhs is not None)
        return self.lhs(extra) or cast("EvalExtra", self.rhs)(extra)


def _parse_extra_item(
    stack,  # type: List[EvalExtra]
    item,  # type: Union[str, List, Tuple]
    marker,  # type: Marker
):
    # type: (...) -> None

    if item == "and":
        stack.append(_And(stack.pop()))
    elif item == "or":
        stack.append(_Or(stack.pop()))
    elif isinstance(item, list):
        for element in item:
            _parse_extra_item(stack, element, marker)
    elif isinstance(item, tuple):
        lhs, op, rhs = item
        if isinstance(lhs, Variable) and "extra" == str(lhs):
            check = lambda extra: _OPERATORS[str(op)](extra, ProjectName(str(rhs)))
        elif isinstance(rhs, Variable) and "extra" == str(rhs):
            check = lambda extra: _OPERATORS[str(op)](extra, ProjectName(str(lhs)))
        else:
            # Any other condition could potentially be true.
            check = lambda _: True
        if stack:
            production_assert(isinstance(stack[-1], _Op))
            cast(_Op, stack[-1]).rhs = check
        else:
            stack.append(check)
    else:
        raise ValueError("Marker is invalid: {marker}".format(marker=marker))


def _parse_extra_check(marker):
    # type: (Marker) -> EvalExtra
    checks = []  # type: List[EvalExtra]
    for item in marker._markers:
        _parse_extra_item(checks, item, marker)
    production_assert(len(checks) == 1)
    return checks[0]


_EXTRA_CHECKS = {}  # type: Dict[str, EvalExtra]


def _parse_marker_for_extra_check(marker):
    # type: (Marker) -> EvalExtra
    maker_str = str(marker)
    eval_extra = _EXTRA_CHECKS.get(maker_str)
    if not eval_extra:
        eval_extra = _parse_extra_check(marker)
        _EXTRA_CHECKS[maker_str] = eval_extra
    return eval_extra


def filter_dependencies(
    requirement,  # type: Requirement
    locked_requirement,  # type: LockedRequirement
):
    # type: (...) -> Iterator[Requirement]

    extras = requirement.extras or [""]
    for dep in locked_requirement.requires_dists:
        if not dep.marker:
            yield dep
        else:
            eval_extra = _parse_marker_for_extra_check(dep.marker)
            if any(eval_extra(ProjectName(extra)) for extra in extras):
                yield dep


def remove_unused_requires_dist(
    resolve_requirements,  # type: Iterable[Requirement]
    locked_resolve,  # type: LockedResolve
):
    # type: (...) -> LockedResolve

    locked_req_by_project_name = {
        locked_req.pin.project_name: locked_req for locked_req in locked_resolve.locked_requirements
    }
    requires_dist_by_locked_req = defaultdict(
        OrderedSet
    )  # type: DefaultDict[LockedRequirement, OrderedSet[Requirement]]
    seen = set()
    requirements = deque(resolve_requirements)
    while requirements:
        requirement = requirements.popleft()
        if requirement in seen:
            continue

        seen.add(requirement)
        locked_req = locked_req_by_project_name.get(requirement.project_name)
        if not locked_req:
            continue

        for dep in filter_dependencies(requirement, locked_req):
            if dep.project_name in locked_req_by_project_name:
                requires_dist_by_locked_req[locked_req].add(dep)
                requirements.append(dep)

    return attr.evolve(
        locked_resolve,
        locked_requirements=SortedTuple(
            attr.evolve(
                locked_requirement,
                requires_dists=SortedTuple(
                    requires_dist_by_locked_req[locked_requirement], key=str
                ),
            )
            for locked_requirement in locked_resolve.locked_requirements
        ),
    )
