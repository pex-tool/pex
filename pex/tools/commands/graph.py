# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import logging
import os
import tempfile
import threading
from argparse import ArgumentParser
from contextlib import contextmanager

from pex.commands.command import OutputMixin, try_open_file, try_run_program
from pex.common import safe_mkdir
from pex.dist_metadata import requires_dists
from pex.pex import PEX
from pex.result import Ok, Result
from pex.tools.command import PEXCommand
from pex.tools.commands.digraph import DiGraph
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import IO, Iterator, Tuple

logger = logging.getLogger(__name__)


class Graph(OutputMixin, PEXCommand):
    """Generates a dot graph of the dependencies contained in a PEX file."""

    @staticmethod
    def _create_dependency_graph(pex):
        # type: (PEX) -> DiGraph
        graph = DiGraph(
            pex.path(),
            fontsize="14",
            labelloc="t",
            label="Dependency graph of {} for interpreter {} ({})".format(
                pex.path(), pex.interpreter.binary, pex.interpreter.identity.requirement
            ),
        )
        marker_environment = pex.interpreter.identity.env_markers.as_dict()
        marker_environment["extra"] = ""
        present_dists = frozenset(dist.project_name for dist in pex.resolve())
        for dist in pex.resolve():
            graph.add_node(
                name=dist.project_name,
                label="{name} {version}".format(name=dist.project_name, version=dist.version),
                URL="https://pypi.org/project/{name}/{version}".format(
                    name=dist.project_name, version=dist.version
                ),
                target="_blank",
            )
            for req in requires_dists(dist):
                if (
                    req.project_name not in present_dists
                    and req.marker
                    and not req.marker.evaluate(environment=marker_environment)
                ):
                    graph.add_node(
                        name=req.project_name,
                        color="lightgrey",
                        style="filled",
                        tooltip="inactive requirement",
                        URL="https://pypi.org/project/{name}".format(name=req.project_name),
                        target="_blank",
                    )
                graph.add_edge(
                    start=dist.project_name,
                    end=req.project_name,
                    label="{specifier}{marker}".format(
                        specifier=req.specifier if req.specifier else "",
                        marker="; {}".format(req.marker) if req.marker else "",
                    )
                    if (req.specifier or req.marker)
                    else None,
                    fontsize="10",
                )
        return graph

    @classmethod
    def add_arguments(cls, parser):
        # type: (ArgumentParser) -> None
        cls.add_output_option(parser, entity="dot graph")
        parser.add_argument(
            "-r",
            "--render",
            action="store_true",
            help="Attempt to render the graph.",
        )
        parser.add_argument(
            "-f",
            "--format",
            default="svg",
            help="The format to render the graph in.",
        )
        parser.add_argument(
            "--open",
            action="store_true",
            help="Attempt to open the graph in the system viewer (implies --render).",
        )
        cls.register_global_arguments(parser)

    def _dot(
        self,
        graph,  # type: DiGraph
        render_fp,  # type: IO
    ):
        # type: (...) -> Result
        read_fd, write_fd = os.pipe()

        def emit():
            with os.fdopen(write_fd, "w") as fp:
                graph.emit(fp)

        emit_thread = threading.Thread(name="{} Emitter".format(__name__), target=emit)
        emit_thread.daemon = True
        emit_thread.start()

        try:
            return try_run_program(
                "dot",
                url="https://graphviz.org/",
                error="Failed to render dependency graph for {}.".format(graph.name),
                args=["-T", self.options.format],
                stdin=read_fd,
                stdout=render_fp,
            )
        finally:
            emit_thread.join()

    @contextmanager
    def _output_for_open(self):
        # type: () -> Iterator[Tuple[IO, str]]
        if self.is_stdout(self.options):
            tmpdir = os.path.join(ENV.PEX_ROOT, "tmp")
            safe_mkdir(tmpdir)
            with tempfile.NamedTemporaryFile(
                prefix="{}.".format(__name__),
                suffix=".deps.{}".format(self.options.format),
                dir=tmpdir,
                delete=False,
            ) as tmp_out:
                yield tmp_out, tmp_out.name
                return

        with self.output(self.options, binary=True) as out:
            yield out, out.name

    def run(self, pex):
        # type: (PEX) -> Result
        graph = self._create_dependency_graph(pex)
        if not (self.options.render or self.options.open):
            with self.output(self.options) as out:
                graph.emit(out)
            return Ok()

        if not self.options.open:
            with self.output(self.options, binary=True) as out:
                return self._dot(graph, out)

        with self._output_for_open() as (out, open_path):
            result = self._dot(graph, out)
            if result.is_error:
                return result

        return try_open_file(
            open_path,
            error="Failed to open dependency graph of {} rendered in {} for viewing.".format(
                pex.path(), open_path
            ),
        )
