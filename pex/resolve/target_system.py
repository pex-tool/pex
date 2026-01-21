# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import operator
import sys

from pex import pex_warnings
from pex.common import pluralize
from pex.compatibility import string
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
from pex.typing import TYPE_CHECKING, Generic, cast

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


class MarkerVisitor(Generic["_C"]):
    def visit_and(
        self,
        marker,  # type: Marker
        context,  # type: _C
    ):
        # type: (...) -> None
        pass

    def visit_or(
        self,
        marker,  # type: Marker
        context,  # type: _C
    ):
        # type: (...) -> None
        pass

    def begin_visit_group(
        self,
        group,  # type: List[Any]
        marker,  # type: Marker
        context,  # type: _C
    ):
        # type: (...) -> Optional[_C]
        return None

    def end_visit_group(
        self,
        group,  # type: List[Any]
        marker,  # type: Marker
        context,  # type: _C
        group_context,  # type: Optional[_C]
    ):
        # type: (...) -> None
        pass

    def visit_op(
        self,
        lhs,  # type: Any
        op,  # type: Any
        rhs,  # type: Any
        marker,  # type: Marker
        context,  # type: _C
    ):
        # type: (...) -> None
        pass


if TYPE_CHECKING:
    _C = TypeVar("_C")


class MarkerParser(Generic["_C"]):
    def __init__(self, visitor):
        # type: (MarkerVisitor["_C"]) -> None
        self._visitor = visitor

    def _parse_marker_item(
        self,
        item,  # type: Union[str, List, Tuple]
        marker,  # type: Marker
        context,  # type: _C
    ):
        # type: (...) -> None

        if item == "and":
            self._visitor.visit_and(marker, context)
        elif item == "or":
            self._visitor.visit_or(marker, context)
        elif isinstance(item, list):
            group_context = self._visitor.begin_visit_group(item, marker, context)
            element_context = group_context if group_context is not None else context
            for element in item:
                self._parse_marker_item(element, marker, element_context)
            self._visitor.end_visit_group(item, marker, context, group_context)
        elif isinstance(item, tuple):
            lhs, op, rhs = item
            self._visitor.visit_op(lhs, op, rhs, marker, context)
        else:
            raise ValueError("Marker is invalid: {marker}".format(marker=marker))

    def parse(
        self,
        marker,  # type: Marker
        context,  # type: _C
    ):
        # type: (...) -> _C

        for item in _marker_items(marker):
            self._parse_marker_item(item, marker, context)
        return context


class HasMarkerVisitor(MarkerVisitor[None]):
    def __init__(self, name):
        # type: (str) -> None
        self._name = name
        self.has_marker = False

    def visit_op(
        self,
        lhs,  # type: Any
        op,  # type: Any
        rhs,  # type: Any
        marker,  # type: Marker
        context,  # type: None
    ):
        # type: (...) -> None
        if self.has_marker:
            return

        for term in lhs, rhs:
            if is_variable(term) and self._name == str(term):
                self.has_marker = True
                break


def has_marker(
    marker,  # type: Marker
    name,  # type: str
):
    # type: (...) -> bool

    visitor = HasMarkerVisitor(name)
    MarkerParser(visitor).parse(marker, None)
    return visitor.has_marker


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

_VERSION_CMP_OPS = {
    "<",
    "<=",
    "==",
    "!=",
    ">=",
    ">",
    "~=",
    "===",
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


@attr.s(frozen=True)
class Values(object):
    @classmethod
    def from_dict(cls, data):
        # type: (Dict[str, Any]) -> Values
        return cls(
            marker_name=data.pop("marker_name"),
            values=tuple(data.pop("values", ())),
            inclusive=data.pop("inclusive", True),
        )

    marker_name = attr.ib()  # type: str
    values = attr.ib(default=())  # type: Tuple[str, ...]
    inclusive = attr.ib(default=True)  # type: bool

    def to_dict(self):
        # type: () -> Dict[str, Any]
        return {"marker_name": self.marker_name, "values": self.values, "inclusive": self.inclusive}

    def apply(self, func):
        # type: (Callable[[str], bool]) -> bool
        if len(self.values) == 0:
            return self.marker_name != "extra"
        if self.inclusive:
            return any(map(func, self.values))
        return all((not result) for result in map(func, self.values))

    def __len__(self):
        # type: () -> int
        return len(self.values)

    def __iter__(self):
        # type: () -> Iterator[str]
        return iter(self.values)


def _get_values_func(marker_name):
    # type: (str) -> Callable[[MarkerEnv], Values]

    if marker_name == "extra":
        return lambda marker_env: Values(marker_name, marker_env.extras)
    elif marker_name == "os_name":
        return lambda marker_env: Values(marker_name, marker_env.os_names)
    elif marker_name == "platform_system":
        return lambda marker_env: Values(marker_name, marker_env.platform_systems)
    elif marker_name == "sys_platform":
        return lambda marker_env: Values(marker_name, marker_env.sys_platforms)
    elif marker_name == "platform_python_implementation":
        return lambda marker_env: Values(marker_name, marker_env.platform_python_implementations)
    elif marker_name == "python_version":
        return lambda marker_env: Values(marker_name, marker_env.python_versions)
    elif marker_name == "python_full_version":
        return lambda marker_env: Values(marker_name, marker_env.python_full_versions)
    return lambda marker_env: marker_env.extra_markers.get_values(marker_name)


class UniversalMarkerVisitor(MarkerVisitor["List[EvalMarker]"]):
    @classmethod
    def parse_marker(cls, marker):
        # type: (Marker) -> EvalMarker

        checks = MarkerParser(cls()).parse(marker, context=[])
        production_assert(len(checks) == 1)
        return checks[0]

    def visit_and(
        self,
        marker,  # type: Marker
        context,  # type: List[EvalMarker]
    ):
        # type: (...) -> None
        context.append(_And(context.pop()))

    def visit_or(
        self,
        marker,  # type: Marker
        context,  # type: List[EvalMarker]
    ):
        # type: (...) -> None
        context.append(_Or(context.pop()))

    def begin_visit_group(
        self,
        group,  # type: List[Any]
        marker,  # type: Marker
        context,  # type: List[EvalMarker]
    ):
        # type: (...) -> Optional[List[EvalMarker]]
        return []

    def end_visit_group(
        self,
        group,  # type: List[Any]
        marker,  # type: Marker
        context,  # type: List[EvalMarker]
        group_context,  # type: Optional[List[EvalMarker]]
    ):
        # type: (...) -> None

        if group_context is None or len(group_context) != 1:
            raise AssertionError(reportable_unexpected_error_msg())

        if context:
            production_assert(isinstance(context[-1], _Op))
            cast(_Op, context[-1]).rhs = group_context[0]
        else:
            context.extend(group_context)

    def visit_op(
        self,
        lhs,  # type: Any
        op,  # type: Any
        rhs,  # type: Any
        marker,  # type: Marker
        context,  # type: List[EvalMarker]
    ):
        # type: (...) -> None

        check = EvalMarkerFunc.create(lhs, op, rhs)
        if context:
            production_assert(isinstance(context[-1], _Op))
            cast(_Op, context[-1]).rhs = check
        else:
            context.append(check)


_MARKER_CHECKS = {}  # type: Dict[Union[Marker, str], EvalMarker]


def _parse_marker(marker):
    # type: (Marker) -> EvalMarker
    eval_marker = _MARKER_CHECKS.get(marker)
    if not eval_marker:
        marker_str = str(marker)
        eval_marker = _MARKER_CHECKS.get(marker_str)
        if not eval_marker:
            eval_marker = UniversalMarkerVisitor.parse_marker(marker)
            _MARKER_CHECKS[marker] = eval_marker
            _MARKER_CHECKS[marker_str] = eval_marker
    return eval_marker


def is_variable(value):
    # type: (Any) -> bool

    if isinstance(value, Variable):
        return True

    # N.B.: This allows interop with Pip vendored packaging which has the same types in a different
    # namespace.
    return type(value).__name__ == "Variable"


class EvalMarkerFunc(object):
    @classmethod
    def create(
        cls,
        lhs,  # type: Any
        op,  # type: Any
        rhs,  # type: Any
    ):
        # type: (...) -> Callable[[MarkerEnv], bool]

        for var, operand, operand_side in ((lhs, rhs, "rhs"), (rhs, lhs, "lhs")):
            if not is_variable(var):
                continue
            marker_name = str(var)
            get_values = _get_values_func(marker_name)
            value = str(operand)
            if marker_name == "extra":
                value = ProjectName(value).normalized
            op_string = str(op)
            operand_side_arg = {operand_side: value}
            return cls(
                get_values=get_values,
                op=op_string,
                is_version_comparison=(
                    marker_name
                    in ("python_version", "python_full_version", "implementation_version")
                    and op_string in _VERSION_CMP_OPS
                ),
                **operand_side_arg
            )

        return lambda _: True

    def __init__(
        self,
        get_values,  # type: Callable[[MarkerEnv], Values]
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
                    bool,
                    version_specifier.contains(
                        # N.B.: This handles `implementation_version` for Python dev releases in the
                        # same way `packaging` does.
                        (value + "local") if value.endswith("+") else value,
                        prereleases=True,
                    ),
                )
            else:
                oper = _OPERATORS[op]
                self._func = lambda value: oper(lhs, value)
        elif rhs is not None:
            if is_version_comparison:
                version_specifier = Specifier("{op}{rhs}".format(op=op, rhs=rhs))
                self._func = lambda value: cast(
                    bool,
                    version_specifier.contains(
                        # N.B.: This handles `implementation_version` for Python dev releases in the
                        # same way `packaging` does.
                        (value + "local") if value.endswith("+") else value,
                        prereleases=True,
                    ),
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

        return self._get_values(marker_env).apply(self._func)


class ExtraMarkersVisitor(MarkerVisitor[str]):
    def __init__(self):
        # type: () -> None
        self.conflicts = OrderedSet()  # type: OrderedSet[str]
        self._marker_values = {}  # type: Dict[str, Tuple[str, OrderedSet[str], bool]]

    def visit_op(
        self,
        lhs,  # type: Any
        op,  # type: Any
        rhs,  # type: Any
        marker,  # type: Marker
        context,  # type: str
    ):
        # type: (...) -> None

        op_symbol = str(op)
        if is_variable(lhs):
            name = str(lhs)
            value = str(rhs)
        elif is_variable(rhs):
            name = str(rhs)
            value = str(lhs)
        else:
            return

        if name in (
            "extra",
            "os_name",
            "platform_system",
            "sys_platform",
            "platform_python_implementation",
            "python_version",
            "python_full_version",
        ):
            return

        if op_symbol == "==":
            requirement, values, inclusive = self._marker_values.setdefault(
                name, (context, OrderedSet(), True)
            )
            if not inclusive:
                self.conflicts.add(
                    "The requirement {context} includes {value} for {name} but the requirement "
                    "{requirement} established {name} as an exclusive set with values: "
                    "{values}.".format(
                        context=context,
                        value=value,
                        name=name,
                        requirement=requirement,
                        values=" ".join(values),
                    )
                )
            else:
                values.add(value)
        elif op_symbol == "!=":
            requirement, values, inclusive = self._marker_values.setdefault(
                name, (context, OrderedSet(), False)
            )
            if inclusive:
                self.conflicts.add(
                    "The requirement {context} excludes {value} for {name} but the requirement "
                    "{requirement} established {name} as an inclusive set with values: "
                    "{values}.".format(
                        context=context,
                        value=value,
                        name=name,
                        requirement=requirement,
                        values=" ".join(values),
                    )
                )
            else:
                values.add(value)
        else:
            pex_warnings.warn(
                "Cannot split universal lock on all clauses of the marker in `{requirement}`.\n"
                "The clause `{lhs} {op} {rhs}` uses comparison `{op}` but only `==` and `!=` are "
                "supported for splitting on '{name}'.\n"
                "Ignoring this clause in split calculations; lock results may be "
                "unexpected.".format(requirement=context, lhs=lhs, op=op, rhs=rhs, name=name)
            )

    def marker_values(self):
        # type: () -> Tuple[Values, ...]
        return tuple(
            Values(marker_name=name, values=tuple(values), inclusive=inclusive)
            for name, (_, values, inclusive) in self._marker_values.items()
        )


@attr.s(frozen=True)
class ExtraMarkers(object):
    @classmethod
    def extract(cls, requirements):
        # type: (Iterable[Tuple[Marker, str]]) -> Optional[ExtraMarkers]

        visitor = ExtraMarkersVisitor()
        marker_parser = MarkerParser(visitor)

        markers = []  # type: List[Marker]
        for marker, provenance in requirements:
            marker_parser.parse(marker, context=provenance)
            markers.append(marker)

        if visitor.conflicts:
            raise ValueError(
                "Encountered {count} {conflicts} when extracting universal lock splits from "
                "top-level requirement markers:\n{items}".format(
                    count=len(visitor.conflicts),
                    conflicts=pluralize(visitor.conflicts, "conflict"),
                    items="\n".join(
                        "{index}. {conflict}".format(index=index, conflict=conflict)
                        for index, conflict in enumerate(visitor.conflicts, start=1)
                    ),
                )
            )

        return cls(markers=tuple(markers), marker_values=visitor.marker_values())

    @classmethod
    def from_dict(cls, data):
        # type: (Dict[str, Any]) -> ExtraMarkers
        return cls(
            markers=tuple(Marker(marker) for marker in data.pop("markers", ())),
            marker_values=tuple(
                Values.from_dict(marker_values) for marker_values in data.pop("marker_values", ())
            ),
        )

    markers = attr.ib(default=())  # type: Tuple[Marker, ...]
    marker_values = attr.ib(default=())  # type: Tuple[Values, ...]

    def to_dict(self):
        # type: () -> Dict[str, Any]
        return {
            "markers": [str(marker) for marker in self.markers],
            "marker_values": [values.to_dict() for values in self.marker_values],
        }

    def get_values(self, marker_name):
        # type: (str) -> Values
        for values in self.marker_values:
            if marker_name == values.marker_name:
                return values
        return Values(marker_name)

    def __iter__(self):
        # type: () -> Iterator[Marker]
        return iter(self.markers)


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
            extras=SortedTuple(ProjectName(extra).normalized for extra in extras),
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
            extra_markers=universal_target.extra_markers if universal_target else ExtraMarkers(),
        )

    extras = attr.ib()  # type: SortedTuple[str]
    os_names = attr.ib()  # type: SortedTuple[str]
    platform_systems = attr.ib()  # type: SortedTuple[str]
    sys_platforms = attr.ib()  # type: SortedTuple[str]
    platform_python_implementations = attr.ib()  # type: SortedTuple[str]
    python_versions = attr.ib()  # type: SortedTuple[str]
    python_full_versions = attr.ib()  # type: SortedTuple[str]
    extra_markers = attr.ib()  # type: ExtraMarkers

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
    # type: (SpecifierSet) -> Optional[str]

    clauses = [
        "python_full_version {operator} '{version}'".format(
            operator=spec.operator, version=spec.version
        )
        for spec in specifier
    ]
    if not clauses:
        return None

    if len(clauses) == 1:
        return clauses[0]

    return "({clauses})".format(clauses=" and ".join(clauses))


@attr.s(frozen=True)
class UniversalTarget(object):
    @classmethod
    def from_dict(cls, data):
        # type: (Dict[str, Any]) -> UniversalTarget

        raw_implementation = data.pop("implementation", None)
        implementation = None  # type: Optional[InterpreterImplementation.Value]
        if raw_implementation:
            if not isinstance(raw_implementation, string):
                raise AssertionError(
                    reportable_unexpected_error_msg(
                        "Expected UniversalTarget `implementation` value to be a str, found "
                        "{value} of type {type}.",
                        value=raw_implementation,
                        type=type(raw_implementation),
                    )
                )
            implementation = InterpreterImplementation.for_value(raw_implementation)

        return cls(
            implementation=implementation,
            requires_python=tuple(
                SpecifierSet(specifier) for specifier in data.pop("requires_python", ())
            ),
            systems=tuple(TargetSystem.for_value(system) for system in data.pop("systems", ())),
            extra_markers=ExtraMarkers.from_dict(data.pop("extra_markers", {})),
        )

    implementation = attr.ib(default=None)  # type: Optional[InterpreterImplementation.Value]
    requires_python = attr.ib(default=())  # type: Tuple[SpecifierSet, ...]
    systems = attr.ib(default=())  # type: Tuple[TargetSystem.Value, ...]
    extra_markers = attr.ib(default=ExtraMarkers())  # type: ExtraMarkers

    def to_dict(self):
        # type: () -> Dict[str, Any]
        return {
            "implementation": str(self.implementation) if self.implementation else None,
            "requires_python": [str(specifier) for specifier in self.requires_python],
            "systems": [str(system) for system in self.systems],
            "extra_markers": self.extra_markers.to_dict(),
        }

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
                universal_target=attr.evolve(
                    self,
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
            python_version_marker = _as_python_version_marker(self.requires_python[0])
            if python_version_marker:
                clauses.append(python_version_marker)
        elif self.requires_python:
            python_version_markers = []  # type: List[str]
            for requires_python in self.requires_python:
                python_version_marker = _as_python_version_marker(requires_python)
                if python_version_marker:
                    python_version_markers.append(python_version_marker)
            clauses.append(
                "({requires_pythons})".format(requires_pythons=" or ".join(python_version_markers))
            )
        clauses.extend("({marker})".format(marker=marker) for marker in self.extra_markers)
        return Marker(" and ".join(clauses)) if clauses else None
