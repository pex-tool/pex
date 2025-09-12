# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import operator

from pex.enum import Enum
from pex.exceptions import production_assert, reportable_unexpected_error_msg
from pex.interpreter_constraints import InterpreterConstraint, iter_compatible_versions
from pex.interpreter_implementation import InterpreterImplementation
from pex.orderedset import OrderedSet
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.third_party.packaging.markers import Marker, Variable
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING, Generic, cast

if TYPE_CHECKING:
    from typing import (
        Any,
        Callable,
        Dict,
        FrozenSet,
        Iterable,
        Iterator,
        List,
        Optional,
        Sequence,
        Tuple,
        TypeVar,
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


def _has_marker(
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
    # type: (str) -> Optional[Tuple[Callable[[MarkerEnv], FrozenSet], Callable[[str], Any]]]

    if marker == "extra":
        return lambda marker_env: marker_env.extras, lambda value: ProjectName(value)
    elif marker == "os_name":
        return lambda marker_env: marker_env.os_names, lambda value: value
    elif marker == "platform_system":
        return lambda marker_env: marker_env.platform_systems, lambda value: value
    elif marker == "sys_platform":
        return lambda marker_env: marker_env.sys_platforms, lambda value: value
    elif marker == "platform_python_implementation":
        return (
            lambda marker_env: marker_env.implementations,
            lambda value: InterpreterImplementation.for_value(value),
        )
    elif marker == "python_version":
        return lambda marker_env: marker_env.python_versions, lambda value: Version(value)
    elif marker == "python_full_version":
        return lambda marker_env: marker_env.python_full_versions, lambda value: Version(value)
    return None


if TYPE_CHECKING:
    _T = TypeVar("_T")


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
                    rhs=operand_type(str(rhs)),
                )

        if isinstance(rhs, Variable):
            value = _get_values_func(str(rhs))
            if value:
                get_values, operand_type = value
                return cls(
                    get_values=get_values,
                    op=_OPERATORS[str(op)],
                    lhs=operand_type(str(lhs)),
                )

        return lambda _: True

    def __init__(
        self,
        get_values,  # type: Callable[[MarkerEnv], Iterable[_T]]
        op,  # type: Callable[[_T, _T], bool]
        lhs=None,  # type: Optional[_T]
        rhs=None,  # type: Optional[_T]
    ):
        # type: (...) -> None

        self._get_values = get_values
        if lhs is not None:
            self._func = lambda value: op(cast("_T", lhs), value)
        elif rhs is not None:
            self._func = lambda value: op(value, cast("_T", rhs))
        else:
            raise ValueError(
                "Must be called with exactly one of lhs or rhs but not both. "
                "Given lhs={lhs} and rhs={rhs}".format(lhs=lhs, rhs=rhs)
            )

    def __call__(self, marker_env):
        # type: (MarkerEnv) -> bool

        values = self._get_values(marker_env)
        return any(map(self._func, values)) if values else True


@attr.s(frozen=True)
class MarkerEnv(object):
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
            extras=frozenset(ProjectName(extra) for extra in (extras or [""])),
            os_names=frozenset(os_names),
            platform_systems=frozenset(platform_systems),
            sys_platforms=frozenset(sys_platforms),
            implementations=frozenset(implementations),
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
    implementations = attr.ib()  # type: FrozenSet[InterpreterImplementation.Value]
    python_versions = attr.ib()  # type: FrozenSet[Version]
    python_full_versions = attr.ib()  # type: FrozenSet[Version]

    def evaluate(self, marker):
        # type: (Marker) -> bool
        eval_marker = _parse_marker(marker)
        return eval_marker(self)


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
            _has_marker(marker, "python_full_version") for marker in markers
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
