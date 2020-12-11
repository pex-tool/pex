# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, IO, List, Mapping, Optional, Tuple

    Value = Optional[str]
    Attributes = Mapping[str, Value]


class DiGraph(object):
    """Renders a dot digraph built up from nodes and edges."""

    @staticmethod
    def _render_ID(value):
        # type: (str) -> str
        # See https://graphviz.org/doc/info/lang.html for the various forms of `ID`.
        return '"{}"'.format(value.replace('"', '\\"'))

    @classmethod
    def _render_a_list(cls, attributes):
        # type: (Attributes) -> str
        # See https://graphviz.org/doc/info/lang.html for the `a_list` production.
        return ", ".join(
            "{name}={value}".format(name=name, value=cls._render_ID(value))
            for name, value in attributes.items()
            if value is not None
        )

    def __init__(
        self,
        name,  # type: str
        strict=True,  # type: bool
        **attributes  # type: Value
    ):
        # type: (...) -> None
        """
        :param name: A name for the graph.
        :param strict: Whether or not duplicate edges are collapsed into one edge.
        """
        self._name = name
        self._strict = strict
        self._attributes = attributes  # type: Attributes
        self._nodes = {}  # type: Dict[str, Attributes]
        self._edges = []  # type: List[Tuple[str, str, Attributes]]

    @property
    def name(self):
        return self._name

    def add_node(
        self,
        name,  # type: str
        **attributes  # type: Value
    ):
        # type: (...) -> None
        """Adds a node to the graph.

        This is done implicitly by add_edge for the nodes the edge connects, but may be useful when
        the node is either isolated or else needs to be decorated with attributes.

        :param name: The name of the node.
        """
        self._nodes[name] = attributes

    def add_edge(
        self,
        start,  # type: str
        end,  # type: str
        **attributes  # type: Value
    ):
        # type: (...) -> None
        """

        :param start: The name of the start node.
        :param end: The name of the end node.
        :param attributes: Any extra attributes for the edge connecting the start node to the end
                           node.
        """
        self._edges.append((start, end, attributes))

    def emit(self, out):
        # type: (IO[str]) -> None
        """Render the current state of this digraph to the given `out` stream.

        :param out: A stream to render this digraph to. N/B.: Will not be flushed or closed.
        """

        def emit_attr_stmt(
            stmt,  # type: str
            attributes,  # type: Attributes
        ):
            # type: (...) -> None
            # See https://graphviz.org/doc/info/lang.html for the `attr_stmt` production.
            out.write(
                "{statement} [{a_list}];\n".format(
                    statement=stmt, a_list=self._render_a_list(attributes)
                )
            )

        if self._strict:
            out.write("strict ")
        out.write("digraph {name} {{\n".format(name=self._render_ID(self._name)))
        emit_attr_stmt("graph", self._attributes)
        for node, attributes in self._nodes.items():
            emit_attr_stmt(self._render_ID(node), attributes)
        for start, end, attributes in self._edges:
            emit_attr_stmt(
                "{start} -> {end}".format(start=self._render_ID(start), end=self._render_ID(end)),
                attributes,
            )
        out.write("}\n")
