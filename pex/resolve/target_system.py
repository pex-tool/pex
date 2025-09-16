# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import operator
import sys

from pex.enum import Enum
from pex.exceptions import production_assert, reportable_unexpected_error_msg
from pex.interpreter_constraints import InterpreterConstraint, iter_compatible_versions
from pex.interpreter_implementation import InterpreterImplementation
from pex.orderedset import OrderedSet
from pex.os import LINUX, MAC, WINDOWS
from pex.pep_503 import ProjectName
from pex.sorted_tuple import SortedTuple
from pex.third_party.packaging.markers import Marker, Variable
from pex.third_party.packaging.specifiers import Specifier, SpecifierSet
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import (
        Any,
        Callable,
        Dict,
        Iterable,
        Iterator,
        List,
        Mapping,
        Optional,
        Sequence,
        Tuple,
        Union,
    )

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class TargetSystem(Enum["TargetSystem.Value"]):
    class Value(Enum.Value):
        pass

    LINUX = Value("linux")
    MAC = Value("mac")
    WINDOWS = Value("windows")

    @classmethod
    def current(cls):
        # type: () -> TargetSystem.Value
        if LINUX:
            return TargetSystem.LINUX
        elif MAC:
            return TargetSystem.MAC
        elif WINDOWS:
            return TargetSystem.WINDOWS
        raise AssertionError(reportable_unexpected_error_msg("Unexpected os {os}", os=sys.platform))


TargetSystem.seal()


def _marker_items(marker):
    # type:(Marker) -> Iterable[Any]

    marker_items = getattr(marker, "_markers", None)
    if marker_items is None:
        raise AssertionError(
            reportable_unexpected_error_msg(
                "Expected packaging.markers.Marker to have a _markers attribute; found none in "
                "{marker} of type {type}",
                marker=marker,
                type=type(marker).__name__,
            )
        )
    production_assert(
        hasattr(marker_items, "__iter__"),
        "Expected packaging.markers.Marker._markers to be iterable; found {marker_items} of type "
        "{type}",
        marker_items=marker_items,
        type=type(marker_items).__name__,
    )
    return cast("Iterable[Any]", marker._markers)


def has_marker(
    marker,  # type: Marker
    name,  # type: str
):
    # type: (...) -> bool

    for item in _marker_items(marker):
        if isinstance(item, tuple):
            lhs, _, rhs = item
            for term in lhs, rhs:
                if isinstance(term, Variable) and name == str(term):
                    return True
    return False


if TYPE_CHECKING:
    EvalMarker = Callable[["MarkerEnv"], bool]


_OPERATORS = {
    "in": lambda lhs, rhs: lhs in rhs,
    "not in": lambda lhs, rhs: lhs not in rhs,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    ">": operator.gt,
}  # type: Mapping[str, Callable[[Any, Any], bool]]


_VERSION_MARKER_OP_FLIPPED = {
    "<": ">",
    "<=": ">=",
    ">=": "<=",
    ">": "<",
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
    # type: (str) -> Optional[Callable[[MarkerEnv], Iterable[str]]]

    if marker == "extra":
        return lambda marker_env: marker_env.extras
    elif marker == "os_name":
        return lambda marker_env: marker_env.os_names
    elif marker == "platform_system":
        return lambda marker_env: marker_env.platform_systems
    elif marker == "sys_platform":
        return lambda marker_env: marker_env.sys_platforms
    elif marker == "platform_python_implementation":
        return lambda marker_env: marker_env.platform_python_implementations
    elif marker == "python_version":
        return lambda marker_env: marker_env.python_versions
    elif marker == "python_full_version":
        return lambda marker_env: marker_env.python_full_versions
    return None


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
        group = []  # type: List[EvalMarker]
        for element in item:
            _parse_marker_item(group, element, marker)
        production_assert(len(group) == 1)
        if stack:
            production_assert(isinstance(stack[-1], _Op))
            cast(_Op, stack[-1]).rhs = group[0]
        else:
            stack.extend(group)
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
    for item in _marker_items(marker):
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


class EvalMarkerFunc(object):
    @classmethod
    def create(
        cls,
        lhs,  # type: Any
        op,  # type: Any
        rhs,  # type: Any
    ):
        # type: (...) -> Callable[[MarkerEnv], bool]

        if isinstance(lhs, Variable):
            marker_name = str(lhs)
            get_values = _get_values_func(marker_name)
            if get_values:
                value = str(rhs)
                if marker_name == "extra":
                    value = ProjectName(value).normalized
                return cls(
                    get_values=get_values,
                    op=str(op),
                    rhs=value,
                    is_version_comparison=marker_name in ("python_version", "python_full_version"),
                )

        if isinstance(rhs, Variable):
            marker_name = str(rhs)
            get_values = _get_values_func(marker_name)
            if get_values:
                value = str(lhs)
                if marker_name == "extra":
                    value = ProjectName(value).normalized
                return cls(
                    get_values=get_values,
                    op=str(op),
                    lhs=value,
                    is_version_comparison=marker_name in ("python_version", "python_full_version"),
                )

        return lambda _: True

    def __init__(
        self,
        get_values,  # type: Callable[[MarkerEnv], Iterable[str]]
        op,  # type: str
        lhs=None,  # type: Optional[str]
        rhs=None,  # type: Optional[str]
        is_version_comparison=False,  # type: bool
    ):
        # type: (...) -> None

        if lhs is not None:
            if is_version_comparison:
                flipped_op = _VERSION_MARKER_OP_FLIPPED.get(op, op)
                version_specifier = Specifier(
                    "{flipped_op}{lhs}".format(lhs=lhs, flipped_op=flipped_op)
                )
                self._func = lambda value: cast(
                    bool, version_specifier.contains(value, prereleases=True)
                )
            else:
                oper = _OPERATORS[op]
                self._func = lambda value: oper(lhs, value)
        elif rhs is not None:
            if is_version_comparison:
                version_specifier = Specifier("{op}{rhs}".format(op=op, rhs=rhs))
                self._func = lambda value: cast(
                    bool, version_specifier.contains(value, prereleases=True)
                )
            else:
                oper = _OPERATORS[op]
                self._func = lambda value: oper(value, rhs)
        else:
            raise ValueError(
                "Must be called with exactly one of lhs or rhs but not both. "
                "Given lhs={lhs} and rhs={rhs}".format(lhs=lhs, rhs=rhs)
            )
        self._get_values = get_values

    def __call__(self, marker_env):
        # type: (MarkerEnv) -> bool

        values = self._get_values(marker_env)
        return any(map(self._func, values)) if values else True


@attr.s(frozen=True)
class MarkerEnv(object):
    @classmethod
    def from_dict(cls, data):
        # type: (Dict[str, Any]) -> MarkerEnv
        return cls(**data)

    @classmethod
    def create(
        cls,
        extras,  # type: Iterable[str]
        universal_target=None,  # type: Optional[UniversalTarget]
    ):
        # type: (...) -> MarkerEnv

        implementations = []  # type: List[InterpreterImplementation.Value]
        if universal_target and universal_target.implementation:
            implementations.append(universal_target.implementation)
        else:
            implementations.extend(InterpreterImplementation.values())

        python_full_versions = (
            list(iter_compatible_versions(universal_target.requires_python))
            if universal_target
            else []
        )
        python_versions = OrderedSet(
            python_full_version[:2] for python_full_version in python_full_versions
        )

        os_names = []
        platform_systems = []
        sys_platforms = []
        target_systems = universal_target.systems if universal_target else ()
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
            extras=SortedTuple(ProjectName(extra).normalized for extra in (extras or [""])),
            os_names=SortedTuple(os_names),
            platform_systems=SortedTuple(platform_systems),
            sys_platforms=SortedTuple(sys_platforms),
            platform_python_implementations=SortedTuple(map(str, implementations)),
            python_versions=SortedTuple(
                ".".join(map(str, python_version)) for python_version in python_versions
            ),
            python_full_versions=SortedTuple(
                ".".join(map(str, python_full_version))
                for python_full_version in python_full_versions
            ),
        )

    extras = attr.ib(converter=SortedTuple, default=SortedTuple())  # type: SortedTuple[str]
    os_names = attr.ib(converter=SortedTuple, default=SortedTuple())  # type: SortedTuple[str]
    platform_systems = attr.ib(
        converter=SortedTuple, default=SortedTuple()
    )  # type: SortedTuple[str]
    sys_platforms = attr.ib(converter=SortedTuple, default=SortedTuple())  # type: SortedTuple[str]
    platform_python_implementations = attr.ib(
        converter=SortedTuple, default=SortedTuple()
    )  # type: SortedTuple[str]
    python_versions = attr.ib(
        converter=SortedTuple, default=SortedTuple()
    )  # type: SortedTuple[str]
    python_full_versions = attr.ib(
        converter=SortedTuple, default=SortedTuple()
    )  # type: SortedTuple[str]

    def as_dict(self):
        # type: () -> Dict[str, Any]
        return attr.asdict(self)

    def evaluate(self, marker):
        # type: (Marker) -> bool
        eval_marker = _parse_marker(marker)
        return eval_marker(self)


def _as_platform_system_marker(system):
    # type: (TargetSystem.Value) -> str

    if system is TargetSystem.LINUX:
        platform_system = "Linux"
    elif system is TargetSystem.MAC:
        platform_system = "Darwin"
    else:
        platform_system = "Windows"

    return "platform_system == '{platform_system}'".format(platform_system=platform_system)


def _as_python_version_marker(specifier):
    # type: (SpecifierSet) -> str

    clauses = [
        "python_full_version {operator} '{version}'".format(
            operator=spec.operator, version=spec.version
        )
        for spec in specifier
    ]
    if not clauses:
        return ""

    if len(clauses) == 1:
        return clauses[0]

    return "({clauses})".format(clauses=" and ".join(clauses))


@attr.s(frozen=True)
class UniversalTarget(object):
    @classmethod
    def from_json(cls, data):
        # type: (Any) -> UniversalTarget
        return cls()

    implementation = attr.ib(default=None)  # type: Optional[InterpreterImplementation.Value]
    requires_python = attr.ib(default=())  # type: Tuple[SpecifierSet, ...]
    systems = attr.ib(default=())  # type: Tuple[TargetSystem.Value, ...]

    def as_json(self):
        # type: () -> Any
        return {}

    def iter_interpreter_constraints(self):
        # type: () -> Iterator[InterpreterConstraint]
        for specifier in self.requires_python:
            yield InterpreterConstraint(specifier=specifier, implementation=self.implementation)

    def are_exhaustive(self, markers):
        # type: (Sequence[Marker]) -> bool

        if len(markers) == 0:
            return True

        use_python_full_version = any(
            has_marker(marker, "python_full_version") for marker in markers
        )
        python_full_versions = tuple(iter_compatible_versions(self.requires_python))
        versions = (
            python_full_versions
            if use_python_full_version
            else tuple(
                OrderedSet(python_full_version[:2] for python_full_version in python_full_versions)
            )
        )
        target_systems = self.systems or TargetSystem.values()
        marker_envs = OrderedSet(
            MarkerEnv.create(
                extras=(),
                universal_target=UniversalTarget(
                    implementation=self.implementation,
                    requires_python=tuple(
                        [SpecifierSet("=={version}".format(version=".".join(map(str, version))))]
                    ),
                    systems=tuple([target_system]),
                ),
            )
            for version in versions
            for target_system in target_systems
        )

        for marker in markers:
            eval_marker = _parse_marker(marker)
            for marker_env in tuple(marker_envs):
                if eval_marker(marker_env):
                    marker_envs.remove(marker_env)
        return not marker_envs

    def marker_env(self, *extras):
        # type: (*str) -> MarkerEnv
        return MarkerEnv.create(extras=extras, universal_target=self)

    def marker(self):
        # type: () -> Optional[Marker]
        clauses = []  # type: List[str]
        if self.systems and frozenset(self.systems) != frozenset(TargetSystem.values()):
            if len(self.systems) == 1:
                clauses.append(_as_platform_system_marker(self.systems[0]))
            else:
                clauses.append(
                    "({clauses})".format(
                        clauses=" or ".join(
                            _as_platform_system_marker(system) for system in self.systems
                        )
                    )
                )
        if self.implementation:
            clauses.append(
                "platform_python_implementation == '{implementation}'".format(
                    implementation=self.implementation
                )
            )
        if len(self.requires_python) == 1:
            clauses.append(_as_python_version_marker(self.requires_python[0]))
        elif self.requires_python:
            clauses.append(
                "({requires_pythons})".format(
                    requires_pythons=" or ".join(
                        _as_python_version_marker(requires_python)
                        for requires_python in self.requires_python
                    )
                )
            )
        return Marker(" and ".join(clauses)) if clauses else None
