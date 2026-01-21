# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.resolve.lockfile import tarjan
from pex.resolve.lockfile.tarjan import Vertex
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable, Iterable, List, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Node(object):
    name = attr.ib()  # type: str
    dependencies = attr.ib(default=())  # type: Tuple[str, ...]


def node(
    name,  # type: str
    dependencies=None,  # type: Optional[List[str]]
):
    # type: (...) -> Node
    return Node(name, tuple(dependencies) if dependencies else ())


def successors_fn(*nodes):
    # type: (*Node) -> Callable[[Node], Iterable[Node]]

    nodes_by_name = {n.name: n for n in nodes}
    return lambda n: tuple(nodes_by_name[name] for name in n.dependencies)


def test_scc_empty():
    dag = tarjan.scc(nodes=(), successors_fn=lambda x: x)
    assert () == dag.vertices
    assert () == dag.roots()


def test_scc_acyclic():
    nodes = (
        node("a", ["b", "c"]),
        node("b", ["d"]),
        node("c", ["d"]),
        node("d"),
    )
    dag = tarjan.scc(nodes=nodes, successors_fn=successors_fn(*nodes))
    assert [
        Vertex(
            node("a", ["b", "c"]),
            components=(node("a", ["b", "c"]),),
            edges=(node("b", ["d"]), node("c", ["d"])),
        ),
        Vertex(
            node("b", ["d"]),
            components=(node("b", ["d"]),),
            edges=(node("d"),),
        ),
        Vertex(
            node("c", ["d"]),
            components=(node("c", ["d"]),),
            edges=(node("d"),),
        ),
        Vertex(
            node("d"),
            components=(node("d"),),
            edges=(),
        ),
    ] == list(dag.vertices)
    assert [node("a", ["b", "c"])] == list(dag.roots())


def test_scc_cyclic_single_tight():
    nodes = (
        node("a", ["b"]),
        node("b", ["a"]),
    )
    dag = tarjan.scc(nodes=nodes, successors_fn=successors_fn(*nodes))
    assert [
        Vertex(node("a", ["b"]), components=(node("a", ["b"]), node("b", ["a"])), edges=())
    ] == list(dag.vertices)
    assert [node("a", ["b"])] == list(dag.roots())


def test_scc_cyclic_single_long():
    nodes = (
        node("a", ["b"]),
        node("b", ["c"]),
        node("c", ["a"]),
    )
    dag = tarjan.scc(nodes=nodes, successors_fn=successors_fn(*nodes))
    assert [
        Vertex(
            node("a", ["b"]),
            components=(node("a", ["b"]), node("b", ["c"]), node("c", ["a"])),
            edges=(),
        )
    ] == list(dag.vertices)
    assert [node("a", ["b"])] == list(dag.roots())


def test_scc_cyclic_single_branch():
    nodes = (
        node("a", ["b"]),
        node("b", ["c"]),
        node("c", ["b"]),
    )
    dag = tarjan.scc(nodes=nodes, successors_fn=successors_fn(*nodes))
    assert [
        Vertex(
            node("a", ["b"]),
            components=(node("a", ["b"]),),
            edges=(node("b", ["c"]),),
        ),
        Vertex(
            node("b", ["c"]),
            components=(node("b", ["c"]), node("c", ["b"])),
            edges=(),
        ),
    ] == list(dag.vertices)
    assert [node("a", ["b"])] == list(dag.roots())


def test_scc_cyclic_multiple_independent_cycle_deps():
    nodes = (
        node("a", ["b", "c"]),
        node("b", ["a", "d"]),
        node("c"),
        node("d"),
    )
    dag = tarjan.scc(nodes=nodes, successors_fn=successors_fn(*nodes))
    assert [
        Vertex(
            node("a", ["b", "c"]),
            components=(node("a", ["b", "c"]), node("b", ["a", "d"])),
            edges=(node("c"), node("d")),
        ),
        Vertex(node("d"), components=(node("d"),), edges=()),
        Vertex(node("c"), components=(node("c"),), edges=()),
    ] == list(dag.vertices)
    assert [node("a", ["b", "c"])] == list(dag.roots())
