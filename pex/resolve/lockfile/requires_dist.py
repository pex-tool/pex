# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import operator
from collections import defaultdict, deque

from pex.dist_metadata import Requirement
from pex.exceptions import production_assert
from pex.interpreter_constraints import iter_compatible_versions
from pex.orderedset import OrderedSet
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import LockedRequirement, LockedResolve, TargetSystem
from pex.sorted_tuple import SortedTuple
from pex.third_party.packaging.markers import Marker, Variable
from pex.typing import TYPE_CHECKING, Generic, cast

if TYPE_CHECKING:
    from typing import (
        Any,
        Callable,
        DefaultDict,
        Dict,
        FrozenSet,
        Iterable,
        Iterator,
        List,
        Optional,
        Tuple,
        Type,
        TypeVar,
        Union,
    )

    import attr  # vendor:skip

    EvalMarker = Callable[["MarkerEnv"], bool]
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class MarkerEnv(object):
    @classmethod
    def create(
        cls,
        extras,  # type: Iterable[str]
        requires_python,  # type: Iterable[str]
        target_systems,  # type: Iterable[TargetSystem.Value]
    ):
        # type: (...) -> MarkerEnv

        python_full_versions = (
            list(iter_compatible_versions(requires_python)) if requires_python else []
        )
        python_versions = OrderedSet(
            python_full_version[:2] for python_full_version in python_full_versions
        )

        os_names = []
        platform_systems = []
        sys_platforms = []
        for target_system in target_systems:
            if target_system is TargetSystem.LINUX:
                os_names.append("posix")
                platform_systems.append("Linux")
                sys_platforms.append("linux")
                sys_platforms.append("linux2")
            elif target_system is TargetSystem.MAC:
                os_names.append("posix")
                platform_systems.append("Darwin")
                sys_platforms.append("darwin")
            elif target_system is TargetSystem.WINDOWS:
                os_names.append("nt")
                platform_systems.append("Windows")
                sys_platforms.append("win32")

        return cls(
            extras=frozenset(ProjectName(extra) for extra in (extras or [""])),
            os_names=frozenset(os_names),
            platform_systems=frozenset(platform_systems),
            sys_platforms=frozenset(sys_platforms),
            python_versions=frozenset(
                Version(".".join(map(str, python_version))) for python_version in python_versions
            ),
            python_full_versions=frozenset(
                Version(".".join(map(str, python_full_version)))
                for python_full_version in python_full_versions
            ),
        )

    extras = attr.ib()  # type: FrozenSet[ProjectName]
    os_names = attr.ib()  # type: FrozenSet[str]
    platform_systems = attr.ib()  # type: FrozenSet[str]
    sys_platforms = attr.ib()  # type: FrozenSet[str]
    python_versions = attr.ib()  # type: FrozenSet[Version]
    python_full_versions = attr.ib()  # type: FrozenSet[Version]


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
        self.lhs = lhs  # type: EvalMarker
        self.rhs = None  # type: Optional[EvalMarker]


class _And(_Op):
    def __call__(self, marker_env):
        # type: (MarkerEnv) -> bool
        production_assert(self.rhs is not None)
        return self.lhs(marker_env) and cast("EvalMarker", self.rhs)(marker_env)


class _Or(_Op):
    def __call__(self, marker_env):
        # type: (MarkerEnv) -> bool
        production_assert(self.rhs is not None)
        return self.lhs(marker_env) or cast("EvalMarker", self.rhs)(marker_env)


def _get_values_func(marker):
    # type: (str) -> Optional[Tuple[Callable[[MarkerEnv], FrozenSet], Type]]

    if marker == "extra":
        return lambda marker_env: marker_env.extras, ProjectName
    elif marker == "os_name":
        return lambda marker_env: marker_env.os_names, str
    elif marker == "platform_system":
        return lambda marker_env: marker_env.platform_systems, str
    elif marker == "sys_platform":
        return lambda marker_env: marker_env.sys_platforms, str
    elif marker == "python_version":
        return lambda marker_env: marker_env.python_versions, Version
    elif marker == "python_full_version":
        return lambda marker_env: marker_env.python_full_versions, Version
    return None


if TYPE_CHECKING:
    _T = TypeVar("_T")


class EvalMarkerFunc(Generic["_T"]):
    @classmethod
    def create(
        cls,
        lhs,  # type: Any
        op,  # type: Any
        rhs,  # type: Any
    ):
        # type: (...) -> Callable[[MarkerEnv], bool]

        if isinstance(lhs, Variable):
            value = _get_values_func(str(lhs))
            if value:
                get_values, operand_type = value
                return cls(
                    get_values=get_values,
                    op=_OPERATORS[str(op)],
                    operand_type=operand_type,
                    rhs=operand_type(rhs),
                )

        if isinstance(rhs, Variable):
            value = _get_values_func(str(rhs))
            if value:
                get_values, operand_type = value
                return cls(
                    get_values=get_values,
                    op=_OPERATORS[str(op)],
                    operand_type=operand_type,
                    lhs=operand_type(lhs),
                )

        return lambda _: True

    def __init__(
        self,
        get_values,  # type: Callable[[MarkerEnv], Iterable[_T]]
        op,  # type: Callable[[_T, _T], bool]
        operand_type,  # type: Callable[[Any], _T]
        lhs=None,  # type: Optional[_T]
        rhs=None,  # type: Optional[_T]
    ):
        # type: (...) -> None

        self._get_values = get_values
        if lhs is not None:
            self._func = lambda value: op(cast("_T", lhs), operand_type(value))
        elif rhs is not None:
            self._func = lambda value: op(operand_type(value), cast("_T", rhs))
        else:
            raise ValueError(
                "Must be called with exactly one of lhs or rhs but not both. "
                "Given lhs={lhs} and rhs={rhs}".format(lhs=lhs, rhs=rhs)
            )

    def __call__(self, marker_env):
        # type: (MarkerEnv) -> bool

        values = self._get_values(marker_env)
        return any(map(self._func, values)) if values else True


def _parse_marker_item(
    stack,  # type: List[EvalMarker]
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
            _parse_marker_item(stack, element, marker)
    elif isinstance(item, tuple):
        lhs, op, rhs = item
        check = EvalMarkerFunc.create(lhs, op, rhs)
        if stack:
            production_assert(isinstance(stack[-1], _Op))
            cast(_Op, stack[-1]).rhs = check
        else:
            stack.append(check)
    else:
        raise ValueError("Marker is invalid: {marker}".format(marker=marker))


def _parse_marker_check(marker):
    # type: (Marker) -> EvalMarker
    checks = []  # type: List[EvalMarker]
    for item in marker._markers:
        _parse_marker_item(checks, item, marker)
    production_assert(len(checks) == 1)
    return checks[0]


_MARKER_CHECKS = {}  # type: Dict[str, EvalMarker]


def _parse_marker(marker):
    # type: (Marker) -> EvalMarker
    maker_str = str(marker)
    eval_marker = _MARKER_CHECKS.get(maker_str)
    if not eval_marker:
        eval_marker = _parse_marker_check(marker)
        _MARKER_CHECKS[maker_str] = eval_marker
    return eval_marker


def filter_dependencies(
    requirement,  # type: Requirement
    locked_requirement,  # type: LockedRequirement
    requires_python=(),  # type: Iterable[str]
    target_systems=(),  # type: Iterable[TargetSystem.Value]
):
    # type: (...) -> Iterator[Requirement]

    marker_env = MarkerEnv.create(
        extras=requirement.extras, requires_python=requires_python, target_systems=target_systems
    )
    for dep in locked_requirement.requires_dists:
        if not dep.marker:
            yield dep
        else:
            eval_marker = _parse_marker(dep.marker)
            if eval_marker(marker_env):
                yield dep


def remove_unused_requires_dist(
    resolve_requirements,  # type: Iterable[Requirement]
    locked_resolve,  # type: LockedResolve
    requires_python=(),  # type: Iterable[str]
    target_systems=(),  # type: Iterable[TargetSystem.Value]
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

        for dep in filter_dependencies(
            requirement, locked_req, requires_python=requires_python, target_systems=target_systems
        ):
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
