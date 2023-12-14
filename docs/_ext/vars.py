# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from docutils import nodes, statemachine
from docutils.parsers.rst import Directive
from sphinx import addnodes
from sphinx.util.nodes import nested_parse_with_titles

from pex.variables import DefaultedProperty, Variables


class Vars(Directive):
    def convert_rst_to_nodes(self, rst_source):
        """Turn an RST string into a node that can be used in the document."""
        node = nodes.Element()
        node.document = self.state.document
        nested_parse_with_titles(
            state=self.state, content=statemachine.ViewList(rst_source.split("\n")), node=node
        )
        return node.children

    def run(self):
        def make_nodes(var_name):
            var_obj = Variables.__dict__[var_name]
            if isinstance(var_obj, DefaultedProperty):
                desc_str = var_obj._func.__doc__
            else:
                desc_str = var_obj.__doc__
            desc_str = desc_str or "NO DESC"

            sig = addnodes.desc()
            sig["objtype"] = sig["desctype"] = "var"
            sig.append(nodes.target("", "", ids=[var_name]))
            sig.append(addnodes.desc_signature(var_name, var_name))

            return [sig] + self.convert_rst_to_nodes(desc_str)

        return [
            node for var in dir(Variables) if var.startswith("PEX_") for node in make_nodes(var)
        ]


def setup(app):
    app.add_directive("vars", Vars)

    return {
        "version": "0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
