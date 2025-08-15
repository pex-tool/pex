# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from collections import OrderedDict, defaultdict

from pex.orderedset import OrderedSet
from pex.typing import TYPE_CHECKING, Generic

if TYPE_CHECKING:
    from typing import Any, Callable, DefaultDict, Iterable, Iterator, List, Tuple, TypeVar

    _N = TypeVar("_N")


class Vertex(Generic["_N"]):
    def __init__(
        self,
        value,  # type: _N
        components,  # type: Tuple[_N, ...]
        edges,  # type: Tuple[_N, ...]
    ):
        # type: (...) -> None
        self.value = value
        self.components = components
        self.edges = edges

    def __eq__(self, other):
        # type: (Any) -> bool
        return type(self) == type(other) and self.value == other.value

    def __ne__(self, other):
        # type: (Any) -> bool
        return not self == other

    def __hash__(self):
        # type: () -> int
        return hash(self.value)

    def __repr__(self):
        if len(self.components) > 1:
            return "Vertex({value}, cycle=({cycle})))".format(
                value=self.value, cycle=", ".join(map(str, self.components))
            )
        return "Vertex({value})".format(value=self.value)


class DirectedAcyclicGraph(Generic["_N"]):
    def __init__(self, nodes):
        # type: (Iterable[Vertex[_N]]) -> None
        self.vertices = tuple(nodes)

    def roots(self):
        # type: () -> Tuple[_N, ...]

        dependants_by_node = defaultdict(list)  # type: DefaultDict[_N, List[Vertex[_N]]]
        for vertex in self.vertices:
            for edge in vertex.edges:
                dependants_by_node[edge].append(vertex)

        return tuple(node.value for node in self.vertices if not dependants_by_node[node.value])


class _Vertex(Generic["_N"]):
    def __init__(self, node):
        # type: (_N) -> None
        self.node = node
        self.successors = OrderedSet()  # type: OrderedSet[_Vertex[_N]]
        self.index = -1
        self.low_link = -1
        self.on_stack = False


class _Scc(Generic["_N"]):
    def __init__(self, vertices):
        # type: (Tuple[_Vertex[_N], ...]) -> None
        self._vertices = vertices
        self._index = 0
        self._stack = []  # type: List[_Vertex[_N]]

    def iter_partitions(self):
        # type: () -> Iterator[Vertex[_N]]
        for vertex in self._vertices:
            if vertex.index == -1:
                for strongly_connected_component in self._strong_connect(vertex):
                    yield strongly_connected_component

    def _strong_connect(self, vertex):
        # type: (_Vertex) -> Iterator[Vertex[_N]]

        vertex.index = self._index
        vertex.low_link = self._index
        self._index += 1
        self._stack.append(vertex)
        vertex.on_stack = True

        for successor in reversed(vertex.successors):
            if successor.index == -1:
                for strongly_connected_component in self._strong_connect(successor):
                    yield strongly_connected_component
                vertex.low_link = min(vertex.low_link, successor.low_link)
            elif successor.on_stack:
                vertex.low_link = min(vertex.low_link, successor.index)

        if vertex.low_link == vertex.index:
            cycle = OrderedDict()  # type: OrderedDict[_N, _Vertex[_N]]
            while self._stack:
                successor = self._stack.pop()
                successor.on_stack = False
                cycle[successor.node] = successor
                if successor == vertex:
                    break
            components = reversed(cycle.items())
            edges = OrderedSet(
                succ.node
                for _, component in components
                for succ in component.successors
                if succ.node not in cycle
            )
            yield Vertex(
                value=vertex.node,
                components=tuple(item[0] for item in components),
                edges=tuple(edges),
            )


def scc(
    nodes,  # type: Iterable[_N]
    successors_fn,  # type: Callable[[_N], Iterable[_N]]
):
    # type: (...) -> DirectedAcyclicGraph[_N]
    """A Tarjan's Strongly Connected Components Algorithm implementation for directed graphs.

    Given all the `nodes` in a graph and a function that can yield the successor nodes (if any) for
    a given node, constructs a directed acyclic graph that isolates cycles in nodes with all
    components that form that cycle.

    See: https://en.wikipedia.org/wiki/Tarjan%27s_strongly_connected_components_algorithm
    """
    vertices_by_node = OrderedDict((n, _Vertex(node=n)) for n in nodes)
    for node, vertex in vertices_by_node.items():
        vertex.successors.update(vertices_by_node[successor] for successor in successors_fn(node))
    strongly_connected_components = _Scc(vertices=tuple(vertices_by_node.values()))
    return DirectedAcyclicGraph(reversed(tuple(strongly_connected_components.iter_partitions())))
